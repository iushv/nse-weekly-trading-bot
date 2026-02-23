import requests
import pandas as pd
import io
import zipfile

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Referer': 'https://www.nseindia.com/',
}

url = 'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260213_F_0000.csv.zip'
r = requests.get(url, headers=headers, timeout=15)
z = zipfile.ZipFile(io.BytesIO(r.content))
df = pd.read_csv(z.open(z.namelist()[0]))
eq = df[df['SctySrs'] == 'EQ']

# Search for each missing symbol by partial name match
missing = ['AEGISCHEM', 'AMARAJABAT', 'GMRINFRA', 'SAILCORP', 'TATAMOTORS', 'VARUNBEV']
keywords = {
    'AEGISCHEM':   'AEGIS',
    'AMARAJABAT':  'AMARA',
    'GMRINFRA':    'GMR',
    'SAILCORP':    'SAIL',
    'TATAMOTORS':  'TATA MOTORS',
    'VARUNBEV':    'VARUN',
}

for old_sym, kw in keywords.items():
    matches = eq[eq['TckrSymb'].str.contains(kw, na=False) |
                 eq['FinInstrmNm'].str.contains(kw, case=False, na=False)]
    print(f'{old_sym} -> candidates:')
    print(matches[['TckrSymb', 'FinInstrmNm', 'ClsPric', 'TtlTradgVol']].to_string())
    print()
