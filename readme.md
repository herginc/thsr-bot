# THSR-Bot

Use [Flask](http://flask.pocoo.org/) to parse HTTP POST messages from websites or line-bot (webhook) and process them.

Keywords: [Flask](http://flask.pocoo.org/), [Flask Source](https://github.com/pallets/flask)


## <span style="color:yellow;">My environments</span>

The program will be developed and tested in the following environments.

### Back-End Server:

1) Microsoft Windows 7 (for local development purpose)
   - support local browser only
   ```
   Python: 3.8.10
   $ python app.py
   ```

2) Ubuntu 24.04 TLS (2026-03-14)
   ```
   # Clone thsr-bot repo：
   $ git clone https://github.com/herginc/thsr-bot.git


   # Install basic packages
   $ sudo apt update
   $ sudo apt install python3 python3-pip python3-venv python-is-python3
   # pip install --upgrade pip
   
   # Create Python virtual environment
   $ cd ~/thsr-bot
   $ python -m venv venv
   $ source venv/bin/activate
   (venv) ~/thsr-bot$
   ```

3) Github codespaces (2026-03-05)
   ```
   Python: 3.12.1
   $ source clean_build.sh
   $ python app.py (working fine)
   
   Known issue:
   $ gunicorn --bind 0.0.0.0:8000 app:app (網頁下單後, Server並沒有處理訂單)
   ```

4) CS50 codespaces (2026-03-09)
   ```
   Python: 3.13.11
   $ source clean_build.sh
   $ python app.py
   Note: setup a forwarding port to external browser

   Known issue:
   $ gunicorn --bind 0.0.0.0:8000 app:app (網頁出不來)
   ```

5) Google Cloud VM - Ubuntu 24.04 TLS
   ```
   Linux 6.8.10 + Python 3.10.12
   $ gunicorn --bind 0.0.0.0:8000 app:app
   ```

### Front-End Client:

1) Browser running on devices with internet access (e.g., Desktop, Laptop, Smart Phone, Tablet, ...)
2) Use natural language in Line-Bot

## <span style="color:yellow;">Design Concept</span>

1. FE client send booking order to BE server via HTTP POST messages
2. BE server create a thread to handle further booking process
3. Client (browser) send '/api/status' request message to server only when active booking order is on-going, or
4. Client (Line-bot) use natural language to forward data to the Back-End Server via webhook, which then calls the AI ​​API to convert the data into booking information in a specific format.

## <span style="color:yellow;">Getting started</span>

```
$ export LINE_CHANNEL_SECRET=YOUR_LINE_CHANNEL_SECRET
$ export LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN

$ pip install -r requirements.txt --ignore-requires-python
```

### Run Flask application - flask-thsr

```
$ python app.py
```

## <span style="color:yellow;">Running on Windows 7</span>

### Setup Python Virtual Environment
```
D:\UserData\Scott\Source\Python>.\thsr-bot\venv\Scripts\activate

(venv) D:\UserData\Scott\Source\Python>python --version
Python 3.8.10

(venv) D:\UserData\Scott\Source\Python>pip --version
pip 25.0.1 from d:\userdata\scott\source\python\thsr-bot\venv\lib\site-packages\pip (python 3.8)

(venv) D:\UserData\Scott\Source\Python>pip list
Package                Version
---------------------- -----------
aenum                  3.1.16
aiohappyeyeballs       2.4.4
aiohttp                3.10.5
aiosignal              1.3.1
annotated-types        0.7.0
async-timeout          4.0.3
attrs                  25.3.0
beautifulsoup4         4.14.2
blinker                1.8.2
certifi                2025.10.5
cffi                   1.17.1
charset-normalizer     3.4.4
click                  8.1.8
colorama               0.4.6
coloredlogs            15.0.1
ddddocr                1.5.6
Deprecated             1.3.1
Flask                  3.0.3
flatbuffers            25.9.23
frozenlist             1.5.0
future                 1.0.0
gevent                 24.2.1
greenlet               3.1.1
gunicorn               23.0.0
humanfriendly          10.0
idna                   3.11
importlib_metadata     8.5.0
itsdangerous           2.2.0
Jinja2                 3.1.6
line-bot-sdk           3.13.0
MarkupSafe             2.1.5
mpmath                 1.3.0
multidict              6.1.0
numpy                  1.24.4
onnxruntime            1.14.1
opencv-python          4.12.0.88
opencv-python-headless 4.12.0.88
packaging              25.0
pillow                 10.4.0
pip                    25.0.1
propcache              0.2.0
protobuf               5.29.5
pycparser              2.23
pydantic               2.10.6
pydantic_core          2.27.2
pyreadline3            3.5.4
python-dateutil        2.9.0.post0
requests               2.32.4
setuptools             56.0.0
six                    1.17.0
soupsieve              2.7
sympy                  1.13.3
typing_extensions      4.13.2
urllib3                2.2.3
Werkzeug               3.0.6
wrapt                  2.0.0
yarl                   1.15.2
zipp                   3.20.2
zope.event             5.0
zope.interface         7.2

```

### Run Back-End Server (Python Flask)
```
(venv) D:\UserData\Scott\Source\Python\thsr-bot>python app.py
```

## <span style="color:yellow;">Running on GitHub Codespace</span>

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

## <span style="color:yellow;">Running on CS50 Codespace</span>

### Installing Python dependencies
```
python -m venv venv
source ./venv/bin/activate
pip install --upgrade pip
pip install -r requirements_thsr_bot.txt --ignore-requires-python
```

### Run Flask app (for development purpose)
```
(venv) /workspaces/projects/thsr-bot/ $ python app.py
```

### Run Gunicorn (for production deployment)
```
(venv) /workspaces/projects/thsr-bot/ $ gunicorn --env DEPLOY_ENV=Render app:app
[2025-10-28 19:37:45 +0800] [24332] [INFO] Starting gunicorn 23.0.0
[2025-10-28 19:37:45 +0800] [24332] [INFO] Listening at: http://127.0.0.1:8000 (24332)
[2025-10-28 19:37:45 +0800] [24332] [INFO] Using worker: sync
[2025-10-28 19:37:45 +0800] [24336] [INFO] Booting worker with pid: 24336
```

### Setup forwarding port

Port forwarding in **CS50.dev** allows a program running on a port inside the cloud environment to be accessed from your web browser through a public URL.

## <span style="color:yellow;">Deploying on Render (Suspend support)</span>

Region: Singapore
Build Command: pip install -r requirements_thsr_bot.txt --ignore-requires-python
Start Command: gunicorn --bind 0.0.0.0:8000 app:app
Instance Type: Free (** Important **)

Auto-Deploy: Off

## <span style="color:yellow;">Appendix</span>

TBD

<pre style="color:yellow;">
This text is yellow.
How to newline without html br tag?
</pre>
<span style="color:red;">This text is red.</span>
<br>
<span style="color:yellow;">
This text is yellow.
How to newline?
</span>
<br>
<span style="color:red;">This text is red.</span>
<p style="color:yellow;white-space: pre-wrap;">
This text is yellow.
How to newline without html br tag?
</p>
