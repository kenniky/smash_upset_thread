import praw
import requests
import json
import sys
import time
import math

ULT_FLAIR = '328ff9f0-9493-11e8-bb38-0eab79b479bc'
MELEE_FLAIR = '4239bb48-9493-11e8-82ac-0e7a476c5a6c'

SMASH_GG_ENDPOINT = 'https://api.smash.gg/gql/alpha'

WINNERS = 'Winners'
LOSERS = 'Losers'

event_slug = ''
upset_differential = 5
top_seed_cutoff = 64
sleep_time = 300

last_unix_time = 1638594000

DISCLAIMER_STRING = 'This post was made and will be updated approximately every {0} minutes by a bot.\n\nUpsets are defined as a top {1} seed losing to a player seeded {2} or more places below them. Notable sets are defined as a top {1} seed losing to a player seeded less than {2} places below them, or a top {1} seed going last game with a player seeded below them. DQs are noted for top {1} seeds.\n\nCharacters will not be added because I have not yet solved computer vision with regards to Smash.'.format(str(sleep_time//60), top_seed_cutoff, upset_differential)

header = ''

def ordinal(num):
    if num % 100 >= 11 and num % 100 <= 13:
        return str(num) + "th"
    if num % 10 == 1:
        return str(num) + "st"
    if num % 10 == 2:
        return str(num) + "nd"
    if num % 10 == 3:
        return str(num) + "rd"
    return str(num) + "th"

def redditify_string(string):
    return string.replace('\\', '\\\\').replace('^', '\\^').replace('_', '\\_').replace('*', '\\*').replace('~', '\\~').replace('>', '\\>').replace('#', '\\#').replace('|', 'l')

def embolden(string):
    return "**" + string + "**"

class Entrant:
    def __init__(self, name, seed):
        self.name = redditify_string(name)
        self.seed = seed

    def __str__(self):
        return embolden(self.name) + " (seed " + str(self.seed) + ")"

class Set:
    WINNER_1 = 1
    WINNER_2 = 2
    WINNER_NONE = 0

    def __init__(self, p1, p2, g1, g2, is_losers, phase, timestamp, winner=None, loser_placement=0):
        self.p1 = p1
        self.p2 = p2
        self.g1 = g1
        self.g2 = g2

        if type(is_losers) == int:
            self.is_losers = is_losers < 0
        else:
            self.is_losers = is_losers

        self.phase = phase
        self.timestamp = timestamp

        if winner == None:
            self.winner = self.WINNER_NONE
        else:
            self.winner = winner 

        self.loser_placement = loser_placement

    def __str__(self):
        if self.winner == self.WINNER_NONE:
            return "unfinished set"

        set_count_str = ""
        if self.g1 == None or self.g2 == None:
            set_count_str = ">"
        elif self.winner == self.WINNER_1:
            set_count_str = str(self.g1) + "-" + str(self.g2)
        else:
            set_count_str = str(self.g2) + "-" + str(self.g1)

        return_str = ""
        if self.winner == self.WINNER_1:
            return_str = str(self.p1) + " " + set_count_str + " " + str(self.p2)
        else:
            return_str = str(self.p2) + " " + set_count_str + " " + str(self.p1)

        if self.is_losers:
            return_str += " [places " + ordinal(self.loser_placement) + "]"

        return return_str

    def get_winner(self):
        if self.winner == self.WINNER_1:
            return self.p1
        else:
            return self.p2

    def get_loser(self):
        if self.winner == self.WINNER_1:
            return self.p2
        else:
            return self.p1

    def get_winner_seed(self):
        if self.winner == self.WINNER_1:
            return self.p1.seed
        else:
            return self.p2.seed

    def get_loser_seed(self):
        if self.winner == self.WINNER_1:
            return self.p2.seed 
        else:
            return self.p1.seed

    def get_winner_score(self):
        if self.winner == self.WINNER_1:
            return self.g1
        else:
            return self.g2

    def get_loser_score(self):
        if self.winner == self.WINNER_1:
            return self.g2
        else:
            return self.g1

def send_request(query, vars):
    json_payload = {
        "query": query,
        "variables": vars
    }
    response = requests.post(SMASH_GG_ENDPOINT, json=json_payload, headers=header)
    if response.status_code != 200:
        print('received non-200 response')
        print(response.json())
        sys.exit()
    return response.json()

def phases_query():
    query = '''query getPhases($eventSlug: String!) {
        event(slug: $eventSlug) {
            phases {
                id
                phaseOrder
            }
        }
    }'''
    variables = '''{{
        "eventSlug": "{}"
    }}'''.format(event_slug)
    return query, variables

def phases_order_query():
    query = '''query getPhases($eventSlug: String!) {
        event(slug: $eventSlug) {
            phases {
                name
                phaseOrder
            }
        }
    }'''
    variables = '''{{
        "eventSlug": "{}"
    }}'''.format(event_slug)
    return query, variables

def seeds_query(page_num=1, per_page=100):
    query = '''query getSeeds($eventSlug: String!, $pageNum: Int!, $perPage: Int!) {
        event(slug: $eventSlug) {
            entrants (query: {
                page: $pageNum
                perPage: $perPage
            }) {
                pageInfo {
                    totalPages
                }
                nodes {
                    name
                    id
                    seeds {
                        phase {
                            id
                        }
                        seedNum
                    }
                }
            }
        }
    }'''
    variables = '''{{
        "eventSlug": "{}",
        "pageNum": {},
        "perPage": {}
    }}'''.format(event_slug, page_num, per_page)
    return query, variables

def sets_query(page_num=1, per_page=60):
    query = '''query getSets($eventSlug: String!, $pageNum: Int!, $perPage: Int!, $time: Timestamp!) {
        event(slug: $eventSlug) {
            sets(
                page: $pageNum,
                perPage: $perPage,
                filters: {
                    state: 3,
                    updatedAfter: $time
                }
            ){
                pageInfo {
                    totalPages
                }
                nodes {
                    id
                    round
                    winnerId
                    slots {
                        standing {
                            stats {
                                score {
                                    value
                                }
                            }
                        }
                        entrant {
                            id
                        }
                    }
                    phaseGroup {
                        phase {
                            name
                        }
                    }
                    completedAt
                }
            }
        }
    }'''
    # print(last_unix_time)
    variables = '''{{
        "eventSlug": "{}",
        "pageNum": {},
        "perPage": {},
        "time": {}
    }}'''.format(event_slug, page_num, per_page, math.floor(last_unix_time))
    return query, variables

def standings_query(page_num=1, per_page=400):
    query = '''query getStandings($eventSlug: String!, $pageNum: Int!, $perPage: Int!) {
        event(slug: $eventSlug) {
            standings(query: {
                page: $pageNum
                perPage: $perPage
            }) {
                pageInfo {
                    totalPages
                }
                nodes {
                    placement
                    entrant {
                        id
                    }
                }
            }
        }
    }'''
    variables = '''{{
        "eventSlug": "{}",
        "pageNum": {},
        "perPage": {}
    }}'''.format(event_slug, page_num, per_page)
    return query, variables

def name_query():
    query = '''query getName($eventSlug: String!) {
        event(slug: $eventSlug) {
            name
            tournament {
                name
            }
        }
    }'''
    variables = '''{{
        "eventSlug": "{}"
    }}'''.format(event_slug)
    return query, variables

def get_first_phase_id():
    phase_query, phase_vars = phases_query()
    phase_response = send_request(phase_query, phase_vars)
    
    phase_list = phase_response['data']['event']['phases']

    if len(phase_list) == 0:
        print('no phases found.')
        sys.exit()

    first_phase_id = phase_list[0]['id']
    first_phase_order = phase_list[0]['phaseOrder']
    for phase in phase_list:
        if phase['phaseOrder'] < first_phase_order:
            first_phase_id = phase['id']
            first_phase_order = phase['phaseOrder']

    return first_phase_id

def get_phase_order():
    phase_query, phase_vars = phases_order_query()
    phase_response = send_request(phase_query, phase_vars)

    phase_list = phase_response['data']['event']['phases']
    ordered_phase_list = []
    lower_bound = 0
    min_phase = phase_list[0]['phaseOrder']
    min_phase_name = phase_list[0]['name']
    phases_left = True

    while phases_left:
        phases_left = False
        for phase in phase_list:
            if min_phase <= lower_bound:
                min_phase = phase['phaseOrder']
                min_phase_name = phase['name']
            if phase['phaseOrder'] > lower_bound:
                phases_left = True
                if phase['phaseOrder'] < min_phase:
                    min_phase = phase['phaseOrder']
                    min_phase_name = phase['name']
        if phases_left:
            ordered_phase_list.append(min_phase_name)
            lower_bound = min_phase

    return ordered_phase_list

def generate_phase_order(sets, sets_data):
    phase_list = []
    for set_id in sets:
        phase = sets_data[set_id].phase
        if phase not in phase_list:
            phase_list.append(phase)

    return phase_list

def get_seeds():
    phase_id = get_first_phase_id()

    seeds_page = 1
    entrants = {}

    while True:
        seed_query, seed_vars = seeds_query(page_num=seeds_page)
        seed_response = send_request(seed_query, seed_vars)

        for entrant in seed_response['data']['event']['entrants']['nodes']:
            name = entrant['name']
            entrant_id = entrant['id']

            for seed in entrant['seeds']:
                if seed['phase']['id'] == phase_id:
                    entrants[entrant_id] = Entrant(name, seed['seedNum'])

        if seeds_page == seed_response['data']['event']['entrants']['pageInfo']['totalPages']:
            break

        seeds_page += 1

    print('retrieved seeds')
    return entrants

def get_final_standings():
    print('retrieving standings...')
    standings_page = 1
    standings = {}

    while True:
        standing_query, standing_vars = standings_query(page_num=standings_page)
        standing_response = send_request(standing_query, standing_vars)

        # print(standing_response)
        print('retrieved {} standings'.format(str(len(standing_response['data']['event']['standings']['nodes']))))

        standings_added = 0

        for standing in standing_response['data']['event']['standings']['nodes']:
            standings[standing['entrant']['id']] = standing['placement']
            standings_added += 1

        print('recorded {} standings'.format(str(standings_added)))

        if standings_page == standing_response['data']['event']['standings']['pageInfo']['totalPages']:
            break

        standings_page += 1

    return standings

def get_newly_finished_sets(standings, seeds, already_logged=[]):
    print('retrieving sets...')
    sets = {}
    sets_page = 1

    before_unix_time = time.time()
    # print(before_unix_time)

    while True:
        set_query, set_vars = sets_query(page_num=sets_page)
        set_response = send_request(set_query, set_vars)

        print('retrieved {} sets'.format(len(set_response['data']['event']['sets']['nodes'])))

        sets_added = 0

        for node in set_response['data']['event']['sets']['nodes']:
            if node['winnerId'] == None:
                continue
            is_losers = node['round'] < 0
            winner = Set.WINNER_1 if node['winnerId'] == node['slots'][0]['entrant']['id'] else Set.WINNER_2

            p1 = seeds[node['slots'][0]['entrant']['id']]
            p2 = seeds[node['slots'][1]['entrant']['id']]

            g1 = node['slots'][0]['standing']['stats']['score']['value']
            g2 = node['slots'][1]['standing']['stats']['score']['value']

            phase = node['phaseGroup']['phase']['name']

            if is_losers:
                loser_id = node['slots'][0]['entrant']['id'] if node['slots'][0]['entrant']['id'] != node['winnerId'] else node['slots'][1]['entrant']['id']
                sets[node['id']] = Set(p1, p2, g1, g2, is_losers, phase, node['completedAt'], winner, standings[loser_id])
            else:
                sets[node['id']] = Set(p1, p2, g1, g2, is_losers, phase, node['completedAt'], winner)

            sets_added += 1

        print('added {} sets to database'.format(str(sets_added)))

        if sets_page >= set_response['data']['event']['sets']['pageInfo']['totalPages']:
            break
        sets_page += 1

    global last_unix_time
    last_unix_time = before_unix_time

    return sets

def get_tournament_name():
    print('retrieving name of tournament...')

    name_quer, name_vars = name_query()
    name_response = send_request(name_quer, name_vars)

    event = name_response['data']['event']

    return event['tournament']['name'], event['name']

def is_upset(set_data):
    return set_data.get_winner_seed() - set_data.get_loser_seed() >= upset_differential

def is_dq(set_data):
    return set_data.g1 == -1 or set_data.g2 == -1

def high_enough_seed(set_data):
    return set_data.get_loser_seed() <= top_seed_cutoff

def is_notable(set_data):
    if set_data.get_winner_seed() > top_seed_cutoff:
        return False
    if set_data.get_winner_seed() - set_data.get_loser_seed() < upset_differential:
        if set_data.get_winner_seed() > set_data.get_loser_seed():
            return True 
        try:
            return set_data.get_winner_score() == set_data.get_loser_score() + 1
        except Exception:
            return False
    return False

def list_sets(sets, sets_data):
    body_str = ''
    winners_sets = []
    losers_sets = []

    phases = generate_phase_order(sets, sets_data)

    for phase in phases:
        winners_upsets = []
        losers_upsets = []

        for upset_id in sets:
            upset = sets_data[upset_id]

            if upset.phase == phase:
                if not upset.is_losers:
                    winners_upsets.append(upset)
                else:
                    losers_upsets.append(upset)

        if len(winners_upsets) == 0 and len(losers_upsets) == 0:
            continue

        # title
        body_str += '#' + phase
        body_str += '\n\n'

        if len(winners_upsets) != 0:
            body_str += '###Winners'
            body_str += '\n'
            for upset in winners_upsets:
                body_str += str(upset)
                body_str += '  \n'
            body_str += '\n'

        if len(losers_upsets) != 0:
            body_str += '###Losers'
            body_str += '\n'
            for upset in losers_upsets:
                body_str += str(upset)
                body_str += '  \n'
            body_str += '\n'

    return body_str

def generate_dqs(winners_dqs_ids, losers_dqs_ids, sets_data):
    body_str = ''

    winners_dqs = []
    losers_dqs = []

    for set_id in winners_dqs_ids:
        winners_dqs.append(sets_data[set_id].get_loser())

    for set_id in losers_dqs_ids:
        losers_dqs.append(sets_data[set_id].get_loser())

    for player in winners_dqs:
        if player in losers_dqs:
            body_str += str(player)
            body_str += '  \n'
        else:
            body_str += str(player)
            body_str += ' (winners)  \n'
    for player in losers_dqs:
        if player not in winners_dqs:
            body_str += str(player)
            body_str += ' (losers)  \n'
    return body_str


def generate_reddit_body(upsets, notables, winners_dqs, losers_dqs, sets_data):
    body_str = DISCLAIMER_STRING + '\n\n'

    if len(upsets) != 0:
        body_str += '---\n\n#Upsets\n\n'

        body_str += list_sets(upsets, sets_data)

    if len(notables) != 0:
        body_str += '---\n\n#Notable Sets\n\n'

        body_str += list_sets(notables, sets_data)

    if len(winners_dqs) != 0 or len(losers_dqs) != 0:
        body_str += '---\n\n#DQs\n\n'

        body_str += generate_dqs(winners_dqs, losers_dqs, sets_data)

    return body_str


if __name__ == '__main__':
    event_slug = input('input event slug: ')
    try:
        upset_differential = int(input('seed differential that counts as an upset: '))
        top_seed_cutoff = int(input('lowest seed that counts as an upset: '))
        sleep_time = int(input('refresh time in seconds: '))
    except ValueError:
        print('you must input a number!')
        sys.exit()

    DISCLAIMER_STRING = 'This post was made and will be updated approximately every {0} minutes by a bot.\n\nUpsets are defined as a top {1} seed losing to a player seeded {2} or more places below them. Notable sets are defined as a top {1} seed losing to a player seeded less than {2} places below them, or a top {1} seed going last game with a player seeded below them. DQs are noted for top {1} seeds.\n\nCharacters will not be added because I have not yet solved computer vision with regards to Smash.'.format(str(sleep_time//60), top_seed_cutoff, upset_differential)

    game = ''
    while game != 'U' and game != 'M':
        game = input('input U for Ultimate, M for Melee: ').upper()

    flair_id = ULT_FLAIR if game == 'U' else MELEE_FLAIR

    ggkeyfile = open('smashgg.key')
    ggkey = ggkeyfile.read()
    ggkeyfile.close()

    header = {"Authorization": "Bearer " + ggkey}

    tournament_name, event_name = get_tournament_name()

    print('event: {} - {}'.format(tournament_name, event_name))

    seeds = get_seeds()

    post_id = input('Enter existing post id (enter none if there isn\'t one): ')

    time.sleep(70) # refresh rate limit

    reddit = praw.Reddit("upsets")
    reddit.validate_on_submit = True

    already_logged = []

    upsets = []
    notables = []
    winners_dqs = []
    losers_dqs = []

    sets_data = {}

    if post_id == 'none':
        # smashbros = reddit.subreddit('smashbros')
        # post = smashbros.submit(title='{} - {} Upset Thread'.format(tournament_name, event_name), selftext=DISCLAIMER_STRING, flair_id=flair_id)

        smashbros = reddit.subreddit('kenniky_sandbox')
        post = smashbros.submit(title='{} - {} Upset Thread'.format(tournament_name, event_name), selftext=DISCLAIMER_STRING)

        print('created post in /r/{} with id {}'.format(smashbros.display_name, post.id))
    else:
        post = praw.models.Submission(reddit, post_id)
        print('editing post in /r/{} with id {}'.format(post.subreddit.display_name, post.id))

    while True:
        standings = get_final_standings()

        sets = get_newly_finished_sets(standings, seeds, already_logged)

        if len(sets) == 0:
            print('no new sets')
        else:
            for set_id, set_data in sets.items():
                if set_id in sets_data.keys():
                    # Clear
                    if set_id in upsets:
                        upsets.remove(set_id)
                    if set_id in notables:
                        notables.remove(set_id)
                    if set_id in losers_dqs:
                        losers_dqs.remove(set_id)
                    if set_id in winners_dqs:
                        winners_dqs.remove(set_id)

                sets_data[set_id] = set_data

                if is_upset(set_data) and high_enough_seed(set_data) and not is_dq(set_data):
                    print('identified {} as upset'.format(set_data))
                    
                    upsets.append(set_id)

                elif is_notable(set_data) and not is_dq(set_data):
                    print('identified {} as notable'.format(set_data))

                    notables.append(set_id)

                elif high_enough_seed(set_data) and is_dq(set_data):
                    print('identified {} as DQ'.format(set_data.get_loser()))
                    if set_data.is_losers:
                        losers_dqs.append(set_id)
                    else:
                        winners_dqs.append(set_id)

                upsets.sort(key=lambda set_id: sets_data[set_id].timestamp)
                notables.sort(key=lambda set_id: sets_data[set_id].timestamp)
                winners_dqs.sort(key=lambda set_id: sets_data[set_id].timestamp)
                losers_dqs.sort(key=lambda set_id: sets_data[set_id].timestamp)

            post.edit(generate_reddit_body(upsets, notables, winners_dqs, losers_dqs, sets_data))

            print('updated post')

        time.sleep(sleep_time)


    # print(standings)



# reddit = praw.Reddit("upsets")
# reddit.validate_on_submit = True

# # subreddit_kenniky_sandbox = reddit.subreddit('kenniky_sandbox')

# # submission = subreddit_kenniky_sandbox.submit(title='TITLE', selftext='some stuff goes HERE')
# # print(submission.id)

# # smashbros = reddit.subreddit('smashbros')
# # post = smashbros.submit(title='TEST POST DONT UPVOTE', selftext='', flair_id=ULT_FLAIR)
# # print(post.id)

# submission = reddit.submission(id='qsmv9l')
# submission.edit('Hello all. ')