# THSR-Bot

Use [Flask](http://flask.pocoo.org/) to parse HTTP POST messages from websites or line-bot (webhook) and process them.

Keywords: [Flask](http://flask.pocoo.org/), [Flask Source](https://github.com/pallets/flask)

## My environments

The program will be developed and tested in the following environments.

Back-End Server:

1) MS Windows 7 + Python 3.8.10  (the program is launched by `python app.py`)
2) Linux 6.8.10 + Python 3.10.12 (the program is launched by `gunicorn --bind 0.0.0.0:8000 app:app`)

Front-End Client:

1) Chrome browser running on Windows PC
2) Chrome browser running on Android Phone

## Design Concept

1. FE client send booking order to BE server via HTTP POST messages
2. BE server create a thread to handle further booking process
3. Client send '/api/status' request message to server only when active booking order is on-going

## Getting started

```
$ export LINE_CHANNEL_SECRET=YOUR_LINE_CHANNEL_SECRET
$ export LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN

$ pip install -r requirements.txt --ignore-requires-python
```

Run Flask application - flask-thsr

```
$ python app.py
```

## Running on GitHub Codespace

### Installing Python dependencies
```
python -m venv venv
source ./venv/bin/activate
pip install --upgrade pip
pip install -r requirements_thsr_bot.txt --ignore-requires-python
```

### Run Gunicorn
```
(venv) /workspaces/projects/thsr-bot/ $ gunicorn --env DEPLOY_ENV=Render app:app
[2025-10-28 19:37:45 +0800] [24332] [INFO] Starting gunicorn 23.0.0
[2025-10-28 19:37:45 +0800] [24332] [INFO] Listening at: http://127.0.0.1:8000 (24332)
[2025-10-28 19:37:45 +0800] [24332] [INFO] Using worker: sync
[2025-10-28 19:37:45 +0800] [24336] [INFO] Booting worker with pid: 24336
```

## Deploying on Render (Suspend support)

Region: Singapore
Build Command: pip install -r requirements_thsr_bot.txt --ignore-requires-python
Start Command: gunicorn --bind 0.0.0.0:8000 app:app
Instance Type: Free (** Important **)

Auto-Deploy: Off

## Appendix

TBD
