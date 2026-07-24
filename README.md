# Bot Telegram — Suivi quotidien d'habitudes avec points

## 1. Créer le bot sur Telegram
1. Ouvre Telegram, cherche **@BotFather**.
2. Envoie `/newbot`, choisis un nom et un identifiant (doit finir par `bot`).
3. BotFather te donne un **token** (ex: `123456:ABC-DEF...`). Copie-le dans `bot.py` à la place de `COLLE_ICI_LE_TOKEN_RECU_DE_BOTFATHER`.

## 2. Récupérer ton identifiant Telegram (pour être admin)
1. Cherche **@userinfobot** sur Telegram et démarre une conversation.
2. Il t'affiche ton `id` numérique. Ajoute-le dans `ADMIN_IDS` dans `bot.py`.

## 3. Installer les dépendances
```bash
python3 -m venv venv
source venv/bin/activate        # sous Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Lancer le bot (test en local)
```bash
python3 bot.py
```
Le bot tourne tant que le terminal reste ouvert. Chaque participant doit :
1. Chercher ton bot sur Telegram (par son @nom d'utilisateur).
2. Envoyer `/start` et donner son nom.
3. Ensuite, il recevra automatiquement chaque soir à **21h00 (heure du Maroc)** un rappel avec un bouton pour voter — ou peut taper `/vote` manuellement à tout moment.

## 5. Commandes disponibles
| Commande | Effet |
|---|---|
| `/start` | Inscription |
| `/vote` | Lancer le sondage du jour |
| `/classement` | Classement du jour |
| `/classement_semaine` | Classement des 7 derniers jours |
| `/export` | Génère et envoie un fichier Excel complet (réservé aux IDs dans `ADMIN_IDS`) |
| `/aide` | Rappel des commandes |

## 6. Faire tourner le bot 24h/24 sans laisser ton ordinateur allumé
Le bot utilise le **polling** (`app.run_polling()`), donc il doit rester actif en permanence sur un serveur. Options réalistes pour ~30 utilisateurs, du plus simple au plus robuste :

- **Un petit VPS pas cher** (ex: OVH, Contabo, Hetzner) : lance le script avec `systemd` ou dans un `screen`/`tmux` pour qu'il survive à la déconnexion SSH. C'est l'option la plus fiable.
- **Railway ou Fly.io** : proposent des offres gratuites/à très bas coût adaptées à un service qui tourne en continu (contrairement à Render gratuit qui met le service en veille, ou PythonAnywhere gratuit qui ne permet pas un polling permanent). Vérifie les conditions actuelles de leur offre gratuite avant de choisir, car elles évoluent régulièrement.
- **Un Raspberry Pi ou vieux PC à la maison** : gratuit, mais dépend de ta connexion internet et de l'électricité.

Sur un VPS Linux, exemple de service `systemd` (`/etc/systemd/system/habitudes-bot.service`) :
```ini
[Unit]
Description=Bot Telegram Suivi Habitudes
After=network.target

[Service]
WorkingDirectory=/chemin/vers/telegram_bot_habitudes
ExecStart=/chemin/vers/telegram_bot_habitudes/venv/bin/python3 bot.py
Restart=always
User=ton_utilisateur

[Install]
WantedBy=multi-user.target
```
Puis :
```bash
sudo systemctl daemon-reload
sudo systemctl enable habitudes-bot
sudo systemctl start habitudes-bot
```

## 7. Sauvegarde des données
Toutes les réponses sont stockées dans `habitudes.db` (SQLite), créé automatiquement à côté de `bot.py`. Pense à faire une copie régulière de ce fichier (ex: `cp habitudes.db backup_$(date +%F).db`) en plus des exports Excel via `/export`.

## Ça marche aussi au-delà de 30 personnes ?
Oui, sans aucune limite de conception : SQLite et python-telegram-bot gèrent facilement plusieurs centaines d'inscrits. La seule contrainte réelle vient de Telegram lui-même, qui limite un bot à environ 30 messages/seconde tous destinataires confondus. Le script espace désormais automatiquement l'envoi du rappel du soir (fonction `envoyer_rappel`) pour rester sous cette limite, que tu aies 30, 300 ou 1000 participants — aucune configuration supplémentaire n'est nécessaire.

## Barème utilisé (repris de ton modèle)
- **Sobh** : جماعة +10 / في الوقت -5 / خارج الوقت -10
- **Salawat** : 4 صلوات +10 / 3 صلوات +5 / صلاتان 0 / صلاة واحدة -5 / ولا صلاة -10
- **Qiyam** : أكثر من 20د +20 / 15-20د +15 / 10-15د +10 / 5-10د +5 / لم أقم -10
- **Wird** : أكثر من حزب +20 / حزب +10 / نصف حزب +5 / لم أقرأ -10
