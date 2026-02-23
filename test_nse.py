import requests

s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/',
})

r1 = s.get('https://www.nseindia.com', timeout=10)
print('Homepage:', r1.status_code)

url = 'https://www.nseindia.com/api/historical/cm/equity'
params = {'symbol': 'TATAMOTORS', 'series': '["EQ"]', 'from': '01-02-2026', 'to': '13-02-2026'}
r2 = s.get(url, params=params, timeout=10)
print('API status:', r2.status_code)
print('Response:', r2.text[:300])
