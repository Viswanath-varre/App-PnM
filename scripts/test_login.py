import urllib.parse, urllib.request
url = 'http://127.0.0.1:5000/login'
data = urllib.parse.urlencode({'email':'admin@example.com','password':'admin123'}).encode()
req = urllib.request.Request(url, data=data)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    body = resp.read().decode('utf-8')
    print('STATUS', resp.getcode())
    print(body[:1000])
except Exception as e:
    print('ERROR', e)
