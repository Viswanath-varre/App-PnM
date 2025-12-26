import urllib.request
urls = [
    'http://127.0.0.1:5000/user/breakdown_reports',
    'http://127.0.0.1:5000/user/dropdown_config'
]
for u in urls:
    try:
        r = urllib.request.urlopen(u, timeout=5)
        print(u, r.status)
        b = r.read(512)
        print(b.decode('utf-8', errors='replace')[:400])
    except Exception as e:
        print('ERROR', u, e)
