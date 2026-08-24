"""
DO DISPLAY NOTIFIER - Surveillance
-----------------------------------
Vérifie toutes les 5 minutes si le contenu des pages One Piece TCG a changé
(nouveau produit, changement de stock...) et envoie une notification push
via ntfy.sh (gratuit, sans compte).

Installation :
    pip install requests beautifulsoup4

Avant de lancer :
    1. Choisis un identifiant secret pour NTFY_TOPIC ci-dessous (change la valeur
       par défaut pour quelque chose d'unique, sinon d'autres personnes qui
       utilisent aussi ntfy.sh pourraient tomber sur tes notifs).
    2. Installe l'app ntfy (iOS / Android) ou ouvre https://ntfy.sh/TON_TOPIC
       dans un navigateur, et abonne-toi à ce topic.
    3. Lance : python monitor.py
    4. Laisse le script tourner (terminal ouvert, ou vois plus bas pour le
       faire tourner sans garder ton ordinateur allumé).
"""

import requests
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# En local : modifie la valeur par défaut ci-dessous.
# Sur GitHub Actions : laisse comme ça, la vraie valeur vient du secret NTFY_TOPIC.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "do-display-notifier-CHANGE-MOI-1234")

# Optionnel : URL d'un webhook Discord, utilisé comme canal de secours en plus
# de ntfy. Laisse vide ("") si tu ne veux pas t'en servir. Comment l'obtenir :
# dans Discord, Paramètres du salon > Intégrations > Webhooks > Nouveau webhook
# > Copier l'URL du webhook.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = "state.json"
CHECK_INTERVAL_SECONDS = 300      # 5 minutes, cadence normale
HOT_CHECK_INTERVAL_SECONDS = 60   # 1 minute, cadence "sortie proche"
HOT_MAX_ROUNDS_PER_RUN = 4        # nb de vérifications rapprochées faites en une seule exécution GitHub Actions
RUN_ONCE = "--once" in sys.argv  # utilisé par le workflow GitHub Actions
TEST_MODE = "--test" in sys.argv  # envoie une fausse alerte, sans vérifier les sites

# Fenêtres de dates autour desquelles on veut vérifier beaucoup plus souvent
# (sortie annoncée, période de restock probable...). Ajoute/modifie librement
# une ligne par édition ou par événement à surveiller de près.
# Format des dates : "AAAA-MM-JJ"
RELEASE_WINDOWS = [
    {
        "label": "OP17 - Les Guerriers les Plus Puissants du Monde",
        "date": "2026-08-28",   # sortie estimée chez les revendeurs français
        "days_before": 30,      # couvre déjà à partir du 29 juillet 2026
        "days_after": 10,       # jusqu'au 7 septembre 2026, pour les restocks post-sortie
    },
]


def is_hot_period() -> bool:
    """True si aujourd'hui tombe dans une des fenêtres de sortie ci-dessus."""
    today = datetime.now().date()
    for window in RELEASE_WINDOWS:
        try:
            target = datetime.strptime(window["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        start = target - timedelta(days=window["days_before"])
        end = target + timedelta(days=window["days_after"])
        if start <= today <= end:
            return True
    return False

# Pages à surveiller. Sur chacune, on regarde si le texte visible change.
SITES = [
    {"name": "Carte One Piece", "url": "https://onepiece-cards.com/pages/articles-en-precommandes"},
    {"name": "Ludisphère", "url": "https://ludisphere.fr/collections/one-piece-card-game-precommande"},
    {"name": "Masterset", "url": "https://masterset.store/collections/one-piece-tcg"},
    {"name": "Le Coin des Barons", "url": "https://lecoindesbarons.com/les-tcg/cartes-onepiece/display-one-piece/"},
    {"name": "PokeZenith", "url": "https://www.pokezenith.com/op17-the-worlds-strongest-warriors/455-one-piece-display-de-24-boosters-op17-les-guerriers-les-plus-puissants-au-monde-4582770058710.html"},
    {"name": "Shop TCG", "url": "https://shop-tcg.fr/product-category/one-piece/"},
    {"name": "Royal TCG", "url": "https://www.royaltcg.shop/onepiece"},
    {"name": "Kyushu TCG", "url": "https://kyushutcg.com/collections/precommandes-one-piece-tcg-japonais"},
    {"name": "1PieceTCG", "url": "https://1piecetcg.fr/collections/all"},
    {"name": "DestockTCG", "url": "https://www.destocktcg.fr/jeux-de-cartes-a-collectionner/one-piece-card-game/"},
    {"name": "ECardStore", "url": "https://ecardstore.fr/"},
    {"name": "Cultura", "url": "https://www.cultura.com/c/collections-one-piece.html"},
    {"name": "Philibert", "url": "https://www.philibertnet.com/fr/15860-one-piece-card-game"},
    {"name": "Hobby Max", "url": "https://www.hobby-max.fr/2318-one-piece"},
    {"name": "Maxi Rêves", "url": "https://maxireves.fr/selection-jeux/jeux-de-cartes-tcg/one-piece-tcg/"},
    {"name": "Les Gentlemen du Jeu", "url": "https://lesgentlemendujeu.com/one-piece-op17-les-guerriers-les-plus-puissants-au-monde/12532-one-piece-display-24-boosters-op17-les-guerriers-les-plus-puissants-au-monde-fr.html"},
    {"name": "PixelHeart", "url": "https://www.pixelheart.eu/fr/produit/one-piece-card-game-boite-de-boosters-francais-display-op17-les-plus-puissants-des-guerriers/"},
    {"name": "Buy the Game", "url": "https://buy-the-game.fr/produit/one-piece-card-game-op17-4th-anniversary-display/"},
    {"name": "Shop OMW", "url": "https://shop.otakusmafiaworld.fr/produit/one-piece-display-24-boosters-op-17/"},
    {"name": "Guizette Family", "url": "https://www.guizettefamily.com/produit/display-one-piece-op17/"},
    {"name": "Shop T Jeux", "url": "https://shoptjeux.com/produit/display-op17-les-guerriers-les-plus-puissants-au-monde-fr/"},
    {"name": "Koala Games", "url": "https://www.koalagames.shop/products/precommande-%e2%9a%94%ef%b8%8f-display-one-piece-op17-les-plus-puissants-des-guerriers-fr"},
    {"name": "L'Antre de Po", "url": "https://lantredepo.com/one-piece-card-game-op-17-display-de-24-boosters-fr/"},
    {"name": "Oupi", "url": "https://oupi.eu/fr/display-one-piece/7367-display-op-17-boite-de-booster-francais-one-piece-card-game.html"},
    {"name": "Givet Jouer", "url": "https://www.givet-jouer.com/blog/cartes-a-collectionner-5/one-piece-op-17-les-guerriers-les-plus-puissants-du-monde-les-precommandes-sont-ouvertes-147"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DoDisplayNotifier/1.0; suivi de stock personnel)"
}

# Mots-clés liés au stock / à la précommande. Si l'un d'eux apparaît ou
# disparaît de la page entre deux vérifications, c'est probablement un vrai
# changement de disponibilité — pas juste une pub ou un bandeau qui tourne.
STOCK_KEYWORDS = [
    "ajouter au panier", "add to cart",
    "en stock", "in stock",
    "précommander", "pré-commander", "pre-order", "preorder",
    "épuisé", "rupture de stock", "out of stock", "sold out",
    "indisponible", "unavailable",
]

# ---------------------------------------------------------------------------
# LOGIQUE
# ---------------------------------------------------------------------------


def fetch_signature(url: str) -> str:
    """Récupère le texte visible d'une page (sans scripts/styles/menus)."""
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text


def keyword_snapshot(text: str) -> dict:
    """Pour chaque mot-clé de stock : None s'il est absent de la page,
    sinon un court extrait du texte autour de sa première occurrence."""
    lower = text.lower()
    snapshot = {}
    for kw in STOCK_KEYWORDS:
        idx = lower.find(kw.lower())
        if idx == -1:
            snapshot[kw] = None
        else:
            start = max(0, idx - 60)
            end = min(len(text), idx + len(kw) + 60)
            snapshot[kw] = text[start:end].strip()
    return snapshot


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def notify(title: str, message: str, url: str) -> None:
    # Canal principal : ntfy (push direct sur le téléphone)
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "urgent",       # son fort + notification qui reste affichée
                "Tags": "rotating_light",   # ajoute une icône 🚨 dans la notif
                "Click": url,               # taper n'importe où sur la notif ouvre la page
                "Actions": f"view, Voir le site, {url}, clear=true",  # bouton dédié
            },
            timeout=10,
        )
    except Exception as e:
        print(f"  (notification ntfy échouée : {e})")

    # Canal de secours : Discord, seulement si un webhook est configuré.
    # Utile si ntfy est en panne, ou juste pour garder une trace dans un salon.
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": f"**{title}**\n{message}\n{url}"},
                timeout=10,
            )
        except Exception as e:
            print(f"  (notification Discord échouée : {e})")


def check_once(state: dict) -> None:
    for site in SITES:
        try:
            text = fetch_signature(site["url"])
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] Erreur en visitant {site['name']} : {e}")
            continue

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        kw_now = keyword_snapshot(text)

        previous = state.get(site["name"])
        if isinstance(previous, dict):
            prev_hash = previous.get("hash")
            prev_kw = previous.get("keywords", {})
            first_visit = False
        else:
            # Ancien format de state.json (juste un hash texte), ou première visite.
            prev_hash = None
            prev_kw = {}
            first_visit = previous is None

        keywords_seen = any(v is not None for v in kw_now.values()) or any(v is not None for v in prev_kw.values())

        changes = []
        if not first_visit:
            if keywords_seen:
                for kw in STOCK_KEYWORDS:
                    now_val = kw_now.get(kw)
                    was_val = prev_kw.get(kw)
                    if (now_val is None) != (was_val is None):
                        if now_val is not None:
                            changes.append(f"« {kw} » est apparu : ...{now_val}...")
                        else:
                            changes.append(f"« {kw} » a disparu de la page")
            elif prev_hash is not None and prev_hash != digest:
                # Repli : aucun mot-clé connu reconnu sur ce site, on retombe
                # sur la détection générique "la page a changé".
                changes.append("Le contenu de la page a changé (aucun mot-clé de stock reconnu ici).")

        if first_visit:
            print(f"[{datetime.now():%H:%M:%S}] {site['name']} : première visite, référence enregistrée.")
        elif changes:
            print(f"[{datetime.now():%H:%M:%S}] >>> Changement détecté sur {site['name']} !")
            notify(
                title=f"🚨 Changement chez {site['name']}",
                message="\n".join(changes),
                url=site["url"],
            )
        else:
            print(f"[{datetime.now():%H:%M:%S}] {site['name']} : rien de nouveau.")

        state[site["name"]] = {"hash": digest, "keywords": kw_now}


if __name__ == "__main__":
    if TEST_MODE:
        print("Mode test : envoi d'une fausse alerte, sans vérifier les vrais sites.")
        notify(
            title="🚨 Test DO DISPLAY NOTIFIER",
            message="Ceci est une notification de test. Si tu la vois (et sur Discord si configuré), le système fonctionne.",
            url="https://github.com/",
        )
        print("Notification de test envoyée.")
        sys.exit(0)

    state = load_state()
    hot = is_hot_period()
    print(f"Surveillance de {len(SITES)} sites.")
    print(f"Notifications envoyées sur le topic ntfy : {NTFY_TOPIC}")
    if hot:
        print("Période de sortie proche détectée -> cadence resserrée (1 min).")

    if RUN_ONCE:
        # Mode GitHub Actions : ce job est de toute façon relancé tout seul
        # toutes les 5 minutes. Hors période chaude, on fait une seule
        # vérification puis on rend la main. En période chaude, on enchaîne
        # plusieurs vérifications rapprochées dans le même run pour se
        # rapprocher d'une cadence d'1 minute sans dépendre d'un cron plus
        # fréquent (GitHub Actions ne descend pas sous 5 minutes).
        rounds = HOT_MAX_ROUNDS_PER_RUN if hot else 1
        for i in range(rounds):
            check_once(state)
            save_state(state)
            if hot and i < rounds - 1:
                time.sleep(HOT_CHECK_INTERVAL_SECONDS)
    else:
        # Mode boucle infinie : utilisé en local, terminal ouvert.
        print("Abonne-toi via https://ntfy.sh/%s ou l'app ntfy. Ctrl+C pour arrêter.\n" % NTFY_TOPIC)
        try:
            while True:
                check_once(state)
                save_state(state)
                interval = HOT_CHECK_INTERVAL_SECONDS if is_hot_period() else CHECK_INTERVAL_SECONDS
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nArrêté.")
