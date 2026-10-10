"""
Recap Montres Hebdo
--------------------
Lit une liste de flux RSS horlogerie, garde les articles des 7 derniers
jours, formate un message et l'envoie sur un canal Telegram.

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
# 1. CONFIGURATION — ajoute/retire des flux RSS ici
# ---------------------------------------------------------------------
RSS_FEEDS = [
    ("Monochrome Watches", "https://monochrome-watches.com/feed/"),
    ("Fratello Watches", "https://www.fratellowatches.com/feed/"),
    ("Hodinkee", "https://www.hodinkee.com/articles.rss"),
]

DAYS_BACK = 7  # fenêtre de temps à couvrir
MAX_ARTICLES_PER_FEED = 5  # évite un message trop long si un flux est très actif

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------------------
# 2. RÉCUPÉRATION DES ARTICLES
# ---------------------------------------------------------------------
def get_recent_entries(feed_url, days_back=DAYS_BACK):
    """Retourne les entrées d'un flux RSS publiées dans les `days_back` derniers jours."""
    feed = feedparser.parse(feed_url)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []

    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue  # on ignore les entrées sans date exploitable

        published_dt = datetime(*published[:6], tzinfo=timezone.utc)
        if published_dt >= cutoff:
            recent.append(
                {
                    "title": entry.get("title", "Sans titre"),
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
            # un flux cassé ne doit pas faire planter tout le script
            print(f"[WARN] Flux '{source_name}' a échoué : {exc}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------
# 3. FORMATAGE DU MESSAGE
# ---------------------------------------------------------------------
def format_message(articles_by_source):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"⌚ *Récap Montres — semaine du {today}*", ""]

    if not articles_by_source:
        lines.append("Rien de notable cette semaine.")
        return "\n".join(lines)

    for source, articles in articles_by_source.items():
        lines.append(f"*{source}*")
        for art in articles:
            lines.append(f"• [{art['title']}]({art['link']})")
        lines.append("")  # ligne vide entre sources

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------
# 4. ENVOI SUR TELEGRAM
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
        "disable_web_page_preview": False,
    }

    response = requests.post(url, data=payload, timeout=15)
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Erreur Telegram : {result}")

    print("Message envoyé avec succès.")


# ---------------------------------------------------------------------
# 5. POINT D'ENTRÉE
# ---------------------------------------------------------------------
def main():
    articles = collect_all_articles()
    message = format_message(articles)
    print(message)  # utile pour voir le résultat dans les logs GitHub Actions
    send_to_telegram(message)


if __name__ == "__main__":
    main()
