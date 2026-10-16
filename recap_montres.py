"""
Recap Montres Hebdo
--------------------
Lit une liste de flux RSS horlogerie, garde les articles des 7 derniers
jours qui parlent de tes marques, formate un message lisible et l'envoie
sur Telegram. Si le message est trop long, il est découpé automatiquement.

Variables d'environnement attendues :
  TELEGRAM_TOKEN  -> le token donné par @BotFather
  TELEGRAM_CHAT_ID -> @tonchannel (public) ou -100xxxxxxxxxx (privé)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import feedparser
import requests

# ---------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------
# Pour ajouter une source : une ligne ("Nom affiché", "adresse du flux").
# Un flux qui ne marche pas est simplement ignoré (voir les logs [WARN]).
RSS_FEEDS = [
    ("Monochrome Watches", "https://monochrome-watches.com/feed/"),
    ("Fratello Watches", "https://www.fratellowatches.com/feed/"),
    ("Hodinkee", "https://www.hodinkee.com/articles.rss"),
    ("Montres Passion", "https://www.montres-passion.fr/feed/"),
    ("A Blog To Watch", "https://www.ablogtowatch.com/feed/"),
    ("Worn & Wound", "https://wornandwound.com/feed/"),
    ("Time+Tide", "https://timeandtidewatches.com/feed/"),
]

# Un emoji par source. Même nom que dans RSS_FEEDS (sinon 📰 par défaut).
SOURCE_EMOJIS = {
    "Monochrome Watches": "🔬",
    "Fratello Watches": "🏁",
    "Hodinkee": "📰",
    "Montres Passion": "🇫🇷",
    "A Blog To Watch": "🔎",
    "Worn & Wound": "🛠️",
    "Time+Tide": "🌊",
}
DEFAULT_EMOJI = "📰"

# Marques à suivre (liste vide = tous les articles, sans filtre)
BRANDS = [
    "Rolex",
    "Omega",
    "Patek Philippe",
    "Audemars Piguet",
    "Cartier",
    "Tudor",
    "Seiko",
    "Grand Seiko",
    "Jaeger-LeCoultre",
    "Vacheron Constantin",
    "IWC",
    "Breitling",
    "TAG Heuer",
    "Panerai",
]

DAYS_BACK = 7
MAX_ARTICLES_PER_FEED = 5

# Telegram refuse les messages de plus de 4096 caractères (petite marge ici).
MAX_MESSAGE_LENGTH = 4000

# True = grande carte d'aperçu pour le premier lien / False = message compact
SHOW_PREVIEW = False

# "Carte d'identité" envoyée aux sites (certains bloquent les robots sans).
USER_AGENT = "Mozilla/5.0 (compatible; CadranBot/1.0)"

SEPARATOR = "━━━━━━━━━━━━━━"
WEEKDAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------------------
# 2. FILTRE PAR MARQUE
# ---------------------------------------------------------------------
def find_brand(title, summary):
    """
    Retourne la marque trouvée dans l'article, ou None si aucune.
    Si BRANDS est vide (pas de filtre), retourne "" (l'article passe).
    """
    if not BRANDS:
        return ""

    text = f"{title} {summary}".lower()
    for brand in BRANDS:
        if brand.lower() in text:
            return brand
    return None


# ---------------------------------------------------------------------
# 3. NETTOYAGE DES TITRES
# ---------------------------------------------------------------------
def clean_title(title):
    """Enlève les caractères qui peuvent casser le format Markdown de Telegram."""
    title = title.replace("[", "(").replace("]", ")")
    for char in ("_", "*", "`"):
        title = title.replace(char, " ")
    return title.strip()


def format_date(dt):
    """Ex : ven. 16/10"""
    return f"{WEEKDAYS_FR[dt.weekday()]} {dt.strftime('%d/%m')}"


# ---------------------------------------------------------------------
# 4. RÉCUPÉRATION DES ARTICLES
# ---------------------------------------------------------------------
def get_recent_entries(feed_url, days_back=DAYS_BACK):
    """
    Retourne (articles_gardés, nombre_d_articles_récents_lus).
    Lève une erreur si le flux est vide ou inaccessible.
    """
    feed = feedparser.parse(feed_url, agent=USER_AGENT)

    if not feed.entries:
        raise RuntimeError("flux vide ou inaccessible (vérifie l'adresse)")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []
    in_window = 0

    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue

        published_dt = datetime(*published[:6], tzinfo=timezone.utc)
        if published_dt < cutoff:
            continue

        in_window += 1

        title = entry.get("title", "Sans titre")
        summary = entry.get("summary", "")

        brand = find_brand(title, summary)
        if brand is None:
            continue  # article hors de nos marques

        recent.append(
            {
                "title": clean_title(title),
                "link": entry.get("link", ""),
                "date": published_dt,
                "brand": brand,
            }
        )

    recent.sort(key=lambda e: e["date"], reverse=True)
    return recent[:MAX_ARTICLES_PER_FEED], in_window


def collect_all_articles():
    """Parcourt tous les flux configurés et renvoie {source: [articles]}."""
    results = {}
    for source_name, url in RSS_FEEDS:
        try:
            entries, in_window = get_recent_entries(url)
            print(
                f"[OK] {source_name} : {in_window} article(s) récent(s), "
                f"{len(entries)} gardé(s) après filtre"
            )
            if entries:
                results[source_name] = entries
        except Exception as exc:
            # un flux cassé ne doit pas faire planter tout le script
            print(f"[WARN] {source_name} ignoré : {exc}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------
# 5. FORMATAGE ET DÉCOUPAGE DU MESSAGE
# ---------------------------------------------------------------------
def format_message(articles_by_source):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"⌚ *Récap Montres — semaine du {today}*", ""]

    if not articles_by_source:
        lines.append("Rien de notable cette semaine sur tes marques.")
        return "\n".join(lines)

    total = 0
    for source, articles in articles_by_source.items():
        emoji = SOURCE_EMOJIS.get(source, DEFAULT_EMOJI)
        lines.append(SEPARATOR)
        lines.append(f"{emoji} *{clean_title(source)}*")
        lines.append("")

        for art in articles:
            total += 1
            details = [format_date(art["date"])]
            if art["brand"]:
                details.append(art["brand"])

            lines.append(f"• [{art['title']}]({art['link']})")
            lines.append(f"   _{' · '.join(details)}_")
            lines.append("")

    lines.append(SEPARATOR)
    pluriel = "s" if total > 1 else ""
    lines.append(f"_{total} article{pluriel} cette semaine_")

    return "\n".join(lines).strip()


def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """Découpe le texte en morceaux <= max_length, en coupant entre deux lignes."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        # Cas rare : une seule ligne plus longue que la limite -> coupe brute
        while len(line) > max_length:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.append(line[:max_length])
            line = line[max_length:]

        if len(current) + len(line) + 1 > max_length:
            chunks.append(current.rstrip())
            current = ""

        current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip())

    return chunks


# ---------------------------------------------------------------------
# 6. ENVOI SUR TELEGRAM
# ---------------------------------------------------------------------
def send_to_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant. "
            "Vérifie tes variables d'environnement / secrets GitHub."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": not SHOW_PREVIEW,
    }

    response = requests.post(url, data=payload, timeout=15)
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Erreur Telegram : {result}")


# ---------------------------------------------------------------------
# 7. POINT D'ENTRÉE
# ---------------------------------------------------------------------
def main():
    articles = collect_all_articles()
    message = format_message(articles)
    print(message)

    chunks = split_message(message)
    for i, chunk in enumerate(chunks, start=1):
        send_to_telegram(chunk)
        print(f"Message {i}/{len(chunks)} envoyé.")


if __name__ == "__main__":
    main()
