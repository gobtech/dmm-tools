"""
Soundcharts API client.
Uses the internal web API (GraphQL + search) with a Bearer token
from an active Soundcharts session.
"""

import os
import csv
import time
import requests

GRAPHQL_URL = 'https://graphql.soundcharts.com/'
SEARCH_URL = 'https://search.soundcharts.com/search/all'

AIRPLAY_QUERY = """
query queryArtistBroadcastGroupList($artistUuid: String!, $limit: Int!, $offset: Int!, $sort: TableSortInput, $filters: [TableFilterInput!]) {
  ArtistBroadcastGroupList(
    artistUuid: $artistUuid
    options: {limit: $limit, offset: $offset, sort: $sort, filters: $filters}
  ) {
    items {
      radioName
      radioSlug
      lastAiredDate
      lastWeeklyPlaysCount
      weeklyEvolution
      weeklyPlaysCount
      monthlyPlaysCount
      yearlyPlaysCount
      countryCode
      timezoneOffset
      song {
        name
        uuid
        __typename
      }
      __typename
    }
    meta {
      hasMore
      __typename
    }
    __typename
  }
}
"""

LATAM_CODES = {
    'AR', 'BR', 'CL', 'CO', 'CR', 'CU', 'DO', 'EC', 'SV', 'GT',
    'HN', 'MX', 'NI', 'PA', 'PY', 'PE', 'PR', 'UY', 'VE', 'BO',
}

# ISO 3166-1 alpha-2 → full country name
COUNTRY_CODE_MAP = {
    'AR': 'Argentina',
    'BR': 'Brazil',
    'CL': 'Chile',
    'CO': 'Colombia',
    'CR': 'Costa Rica',
    'CU': 'Cuba',
    'DO': 'Dominican Republic',
    'EC': 'Ecuador',
    'SV': 'El Salvador',
    'GT': 'Guatemala',
    'HN': 'Honduras',
    'MX': 'Mexico',
    'NI': 'Nicaragua',
    'PA': 'Panama',
    'PY': 'Paraguay',
    'PE': 'Peru',
    'PR': 'Puerto Rico',
    'UY': 'Uruguay',
    'VE': 'Venezuela',
    'BO': 'Bolivia',
    'US': 'United States',
    'CA': 'Canada',
    'GB': 'United Kingdom',
    'DE': 'Germany',
    'FR': 'France',
    'ES': 'Spain',
    'IT': 'Italy',
    'PT': 'Portugal',
    'NL': 'Netherlands',
    'BE': 'Belgium',
    'AT': 'Austria',
    'CH': 'Switzerland',
    'SE': 'Sweden',
    'NO': 'Norway',
    'DK': 'Denmark',
    'FI': 'Finland',
    'PL': 'Poland',
    'CZ': 'Czech Republic',
    'RO': 'Romania',
    'HU': 'Hungary',
    'GR': 'Greece',
    'TR': 'Turkey',
    'RU': 'Russia',
    'UA': 'Ukraine',
    'IE': 'Ireland',
    'AU': 'Australia',
    'NZ': 'New Zealand',
    'JP': 'Japan',
    'KR': 'South Korea',
    'IN': 'India',
    'ZA': 'South Africa',
    'IL': 'Israel',
    'AE': 'United Arab Emirates',
    'SA': 'Saudi Arabia',
    'EG': 'Egypt',
    'NG': 'Nigeria',
    'KE': 'Kenya',
    'PH': 'Philippines',
    'TH': 'Thailand',
    'ID': 'Indonesia',
    'MY': 'Malaysia',
    'SG': 'Singapore',
    'TW': 'Taiwan',
    'HK': 'Hong Kong',
    'CN': 'China',
    'SK': 'Slovakia',
    'BG': 'Bulgaria',
    'HR': 'Croatia',
    'RS': 'Serbia',
    'SI': 'Slovenia',
    'LT': 'Lithuania',
    'LV': 'Latvia',
    'EE': 'Estonia',
    'IS': 'Iceland',
    'LU': 'Luxembourg',
    'MT': 'Malta',
    'CY': 'Cyprus',
}


def get_token():
    """Get Soundcharts Bearer token from environment."""
    token = os.environ.get('SOUNDCHARTS_TOKEN', '').strip()
    if not token:
        return None
    return token


def search_artist(name, token=None):
    """
    Search for an artist on Soundcharts.
    Returns the best match: { name, uuid, slug, countryCode, genres }
    or None if not found.
    """
    headers = {
        'Accept': '*/*',
        'Origin': 'https://app.soundcharts.com',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    resp = requests.get(
        SEARCH_URL,
        params={'query': name, 'size': 10},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get('sResults', {}).get('artist', {}).get('results', [])
    if not results:
        return None

    # Return the top match (highest score)
    best = results[0]
    return {
        'name': best.get('name', ''),
        'uuid': best.get('uuid', ''),
        'slug': best.get('slug', ''),
        'countryCode': best.get('countryCode', ''),
        'genres': best.get('genres', []),
    }


def fetch_airplay_data(artist_uuid, token, sort_by='monthlyPlaysCount', region=None, log_fn=None):
    """
    Fetch all airplay data for an artist from Soundcharts.
    Paginates through all results.
    region: 'latam' to filter to LATAM countries only, None for all.
    Returns list of dicts with: song, station, plays_28d, country
    """
    if log_fn is None:
        log_fn = print

    filter_codes = None
    if region == 'latam':
        filter_codes = LATAM_CODES

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Origin': 'https://app.soundcharts.com',
    }

    all_items = []
    limit = 50

    # When filtering by region, fetch per-country via the API's server-side
    # filter so we get ALL results.  The API's TableFilterInput only accepts
    # a single `term` per filter, so we iterate country codes.
    country_groups = sorted(filter_codes) if filter_codes else [None]

    for country_code in country_groups:
        api_filters = []
        if country_code:
            api_filters = [{'column': 'countryCode', 'term': country_code}]

        offset = 0
        page = 0
        country_label = COUNTRY_CODE_MAP.get(country_code, country_code) if country_code else 'all'

        while True:
            page += 1
            payload = {
                'operationName': 'queryArtistBroadcastGroupList',
                'query': AIRPLAY_QUERY,
                'variables': {
                    'artistUuid': artist_uuid,
                    'limit': limit,
                    'offset': offset,
                    'filters': api_filters,
                    'sort': {'on': sort_by, 'dir': 'desc'},
                },
            }

            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 401:
                    log_fn("Error: Soundcharts token expired or invalid. Please update SOUNDCHARTS_TOKEN in .env")
                    return None
                log_fn(f"Error fetching {country_label} page {page}: {e}")
                break
            except Exception as e:
                log_fn(f"Error fetching {country_label} page {page}: {e}")
                break

            broadcast_data = data.get('data', {}).get('ArtistBroadcastGroupList', {})
            items = broadcast_data.get('items', [])
            meta = broadcast_data.get('meta', {})

            if not items:
                break

            for item in items:
                cc = item.get('countryCode', '')
                country_name = COUNTRY_CODE_MAP.get(cc, cc)

                song_name = ''
                song_uuid = ''
                song_data = item.get('song')
                if song_data:
                    song_name = song_data.get('name', '')
                    song_uuid = song_data.get('uuid', '')

                all_items.append({
                    'song': song_name,
                    'song_uuid': song_uuid,
                    'station': item.get('radioName', ''),
                    'plays_28d': item.get('monthlyPlaysCount', 0),
                    'country': country_name,
                    'weekly_plays': item.get('weeklyPlaysCount', 0),
                    'prev_weekly_plays': item.get('lastWeeklyPlaysCount', 0),
                    'yearly_plays': item.get('yearlyPlaysCount', 0),
                    'weekly_evolution': item.get('weeklyEvolution', 0),
                    'last_aired': item.get('lastAiredDate', ''),
                })

            if not meta.get('hasMore', False):
                break

            offset += limit
            time.sleep(0.3)  # Rate limit courtesy

        if country_code and all_items:
            # Only log countries that had results to keep output clean
            count_for_country = sum(1 for i in all_items if i['country'] == country_label)
            if count_for_country:
                log_fn(f"  {country_label}: {count_for_country} stations")
        elif not country_code:
            log_fn(f"  Page {page}: {len(items)} stations (total: {len(all_items)})")

        time.sleep(0.2)  # Rate limit courtesy between countries

    return all_items


SONG_BROADCAST_QUERY = """
query querySongBroadcastTopBroadcastPlayList($songUuid: String!, $startDate: String!, $endDate: String!, $countryCode: String, $offset: Int!, $limit: Int!) {
  SongBroadcastTopBroadcastPlayList(
    songUuid: $songUuid
    startDate: $startDate
    endDate: $endDate
    countryCode: $countryCode
    offset: $offset
    limit: $limit
  ) {
    totalPlays
    totalCount
    plots {
      radioName
      radioSlug
      countryCode
      playsCount
      __typename
    }
    __typename
  }
}
"""


def fetch_song_custom_range(song_uuid, token, start_date, end_date, country_codes=None, log_fn=None):
    """
    Fetch station-level play counts for a single song over a custom date range.
    Uses the SongBroadcastTopBroadcastPlayList query.
    country_codes: set of ISO codes to filter (e.g. LATAM_CODES), or None for all.
    Returns list of dicts: { station, plays, country, country_code }
    """
    if log_fn is None:
        log_fn = print

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Origin': 'https://app.soundcharts.com',
    }

    all_items = []
    limit = 100

    # When filtering by region, iterate per country code
    code_groups = sorted(country_codes) if country_codes else [None]

    for cc in code_groups:
        offset = 0
        cc_label = COUNTRY_CODE_MAP.get(cc, cc) if cc else 'all'

        while True:
            variables = {
                'songUuid': song_uuid,
                'startDate': start_date,
                'endDate': end_date,
                'offset': offset,
                'limit': limit,
            }
            if cc:
                variables['countryCode'] = cc

            payload = {
                'operationName': 'querySongBroadcastTopBroadcastPlayList',
                'query': SONG_BROADCAST_QUERY,
                'variables': variables,
            }

            try:
                resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError:
                if resp.status_code == 401:
                    log_fn("Error: Soundcharts token expired or invalid.")
                    return None
                log_fn(f"Error fetching custom range for {cc_label}: HTTP {resp.status_code}")
                break
            except Exception as e:
                log_fn(f"Error fetching custom range for {cc_label}: {e}")
                break

            result = data.get('data', {}).get('SongBroadcastTopBroadcastPlayList', {})
            plots = result.get('plots', [])

            if not plots:
                break

            for p in plots:
                p_cc = p.get('countryCode', '')
                all_items.append({
                    'station': p.get('radioName', ''),
                    'plays': p.get('playsCount', 0),
                    'country': COUNTRY_CODE_MAP.get(p_cc, p_cc),
                    'country_code': p_cc,
                })

            # If we got fewer than limit, no more pages
            if len(plots) < limit:
                break

            offset += limit
            time.sleep(0.3)

        time.sleep(0.2)

    return all_items


def airplay_to_csv(airplay_data, output_path):
    """
    Write airplay data to a CSV file in the format expected by the
    radio report generator: Song, Station, 28D, Country
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Song', 'Station', '28D', 'Country'])
        for item in airplay_data:
            if item['plays_28d'] > 0 and item['song'] and item['station']:
                writer.writerow([
                    item['song'],
                    item['station'],
                    item['plays_28d'],
                    item['country'],
                ])
    return output_path
