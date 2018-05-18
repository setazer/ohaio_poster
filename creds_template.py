# -*- coding: utf-8 -*-
# VK config
from os import getcwd
VK_TOKEN = ''
VK_LOGIN= ''
VK_PASS= ''
VK_GROUP_ID = '123456' # https://vk.com/club123456
VK_APP_ID = '123456'

# Tumblr config
TUMBLR_CONSUMER_KEY = ''
TUMBLR_CONSUMER_SECRET = ''
TUMBLR_OAUTH_TOKEN = ''
TUMBLR_OAUTH_SECRET = ''
TUMBLR_BLOG_NAME = 'sample-blog'

# SQL database config
DB_USER = 'user'
DB_PASSWORD = 'passWORD1234'
DB_HOST = 'localhost'
DB_NAME = 'db_sample'
DB_PORT = '3306' # default mysql port

# Telegram config
TELEGRAM_TOKEN = '' # get it from https://t.me/botfather
TELEGRAM_CHANNEL = '' # channel id for posting pictures to
TELEGRAM_CHANNEL_MON = '' # channel id where OhaioMonitor posts suggested pictures
TELEGRAM_CHANNEL_VKUPDATES = '' #  channel id where OhaioVKUpdates posts stuff happening in VK Group
TELEGRAM_PROXY = {}
#    "http": "proxy.antizapret.prostovpn.org:3128",
#    "https": "proxy.antizapret.prostovpn.org:3128"
#}
OWNER_ROOM_ID = '' # bot owner telegram id

# CherryPy config
WEBHOOK_HOST = 'host.name'
WEBHOOK_PORT = 8443 # 80/443/88/8443
WEBHOOK_LISTEN = '0.0.0.0'
WEBHOOK_SSL_CERT = getcwd()+'/webhook_cert.pem' # Generate it with "openssl genrsa -out webhook_pkey.pem 2048"
WEBHOOK_SSL_PRIV = getcwd()+'/webhook_pkey.pem' # Generate it with "openssl req -new -x509 -days 3650 -key webhook_pkey.pem -out webhook_cert.pem"
WEBHOOK_URL_BASE = "https://{}:{}".format(WEBHOOK_HOST, WEBHOOK_PORT)
WEBHOOK_URL_PATH = "/{}/".format(TELEGRAM_TOKEN)

# Misc
MONITOR_FOLDER = getcwd()+'/pics/mon/'
QUEUE_FOLDER = getcwd()+'/pics/q/'
LOG_FILE = 'Ohaio.log'
SERVICE_DEFAULT = 'dan'
ERROR_LOGS_DIR = getcwd()+'/errlogs/'
QUEUE_GEN_FILE = getcwd()+'/queue_grid.png'
BANNED_TAGS = ['comic'] # OhaioMonitor banned tags (danbooru api doesnt allow requests for more tan 2 tags, workaround)
service_db = {'gel':{'name':'Gelbooru',
                     'post_url':'gelbooru.com/index.php?page=post&s=view&id=',
                     'post_api':'gelbooru.com/index.php?page=dapi&s=post&q=index&id=',
                     'posts_api':'gelbooru.com/index.php?page=dapi&s=post&q=index&tags=',
                     'tag_api':'gelbooru.com/index.php?page=dapi&s=tag&q=index&names=',
                     'login_url':'gelbooru.com/index.php?page=account&s=login&code=00',
                     'payload':{'user': 'username',
                                'pass': 'passWORD',
                                'submit': 'Log in'}},
              'dan': {'name': 'Danbooru',
                      'base_url': 'danbooru.donmai.us',
                      'artist_api':'danbooru.donmai.us/artists.json?search[name]={}',
                      'post_url': 'danbooru.donmai.us/posts/',
                      'post_api': 'danbooru.donmai.us/posts/{}.json',
                      'posts_api': 'danbooru.donmai.us/posts.json?tags={}',
                      'tag_api': '',
                      'login_url': 'danbooru.donmai.us/session/new',
                      'payload': {'user': 'username',
                                  'api_key': 'API_key',
                                  'commit':'Submit'}}}
              # 'new': {'name': '',
              #         'post_url': '',
              #         'post_api': '',
              #         'tag_api': '',
              #         'login_url': 'gelbooru.com/index.php?page=account&s=login&code=00',
              #         'payload': {'user': '',
              #                     'pass': '',
              #                     'submit': 'Log in'}}
