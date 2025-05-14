import requests
from datetime import datetime, timedelta

API_KEY = 'YOUR_API_KEY'

def get_location_id(city_name: str) -> str:
    url = 'https://api.maersk.com/synergy/reference-data/geography/locations'
    params = {'cityName': city_name, 'type': 'city'}
    headers = {'consumer-key': API_KEY}

    response = requests.get(url, params=params, headers=headers)
    data = response.json()
    return data['data'][0]['id']  # 最初の候補のIDを返す

def get_schedule(from_city: str, to_city: str, from_date: str):
    from_id = get_location_id(from_city)
    to_id = get_location_id(to_city)

    url = 'https://api.maersk.com/synergy/sailing-schedules'
    params = {
        'from': from_id,
        'to': to_id,
        'fromDate': from_date,
        'toDate': (datetime.strptime(from_date, '%Y-%m-%d') + timedelta(days=30)).strftime('%Y-%m-%d')
    }
    headers = {'consumer-key': API_KEY}

    response = requests.get(url, params=params, headers=headers)
    return response.json()

# 使用例
schedules = get_schedule("Tokyo", "Los Angeles", "2025-05-01")
for s in schedules.get('data', []):
    print(f"Vessel: {s['vesselName']}, ETD: {s['etd']}, ETA: {s['eta']}")
