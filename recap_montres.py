"""
Recap Montres Hebdo
--------------------
Lit une liste de flux RSS horlogerie, garde les articles des 7 derniers
jours qui parlent de tes marques, formate un message et l'envoie sur Telegram.
Si le message est trop long, il est découpé automatiquement en plusieurs.

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
RSS_FEEDS = [
    ("Monochrome Watches", "https://monochrome-watches.com/feed/"),
    ("Fratello Watches", "https://www.fratellowatches.com/feed/"),
    ("Hodinkee", "https://www.hodinkee.com/articles.rss"),
]

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

# Telegram refuse les messages de plus de 4096 caractères.
# On garde une petite marge de sécurité.
MAX_MESSAGE_LENGTH = 300

# True = Telegram affiche une grande carte d'aperçu pour le premier lien
# False = message plus compact, sans aperçu
SHOW_PREVIEW = False

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------------------
# 2. FILTRE PAR MARQUE
# ---------------------------------------------------------------------
def matches_brands(title, summary):
    """Retourne True si l'article parle d'une de nos marques (ou si pas de filtre)."""
    if not BRANDS:
        return True

    text = f"{title} {summary}".lower()
    return any(brand.lower() in text for brand in BRANDS)


# ---------------------------------------------------------------------
# 3. NETTOYAGE DES TITRES
# ---------------------------------------------------------------------
def clean_title(title):
    """Enlève les caractères qui peuvent casser le format Markdown de Telegram."""
    title = title.replace("[", "(").replace("]", ")")
    for char in ("_", "*", "`"):
        title = title.replace(char, " ")
    return title.strip()


# ---------------------------------------------------------------------
# 4. RÉCUPÉRATION DES ARTICLES
# ---------------------------------------------------------------------
def get_recent_entries(feed_url, days_back=DAYS_BACK):
    """Retourne les entrées récentes d'un flux RSS qui parlent de nos marques."""
    feed = feedparser.parse(feed_url)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []

    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue

        published_dt = datetime(*published[:6], tzinfo=timezone.utc)
        if published_dt < cutoff:
            continue

        title = entry.get("title", "Sans titre")
        summary = entry.get("summary", "")

        if not matches_brands(title, summary):
            continue

        recent.append(
            {
                "title": clean_title(title),
                "link": entry.get("link", ""),
                "date": published_dt,
            }
        )

    recent.sort(key=lambda e: e["date"], reverse=True)
    return recent[:MAX_ARTICLES_PER_FEED]


def collect_all_articles():
    """Parcourt tous les flux configurés et renvoie {source: [articles]}."""
    results = {}
    for source_name, url in RSS_FEEDS:
        try:
            entries = get_recent_entries(url)
            if entries:
                results[source_name] = entries
        except Exception as exc:
            print(f"[WARN] Flux '{source_name}' a échoué : {exc}", file=sys.stderr)
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

    for source, articles in articles_by_source.items():
        lines.append(f"*{source}*")
        for art in articles:
            lines.append(f"• [{art['title']}]({art['link']})")
        lines.append("")

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
