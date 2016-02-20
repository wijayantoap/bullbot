import logging
import datetime

from pajbot.modules import BaseModule, ModuleSetting
from pajbot.models.command import Command
from pajbot.models.handler import HandlerManager

import requests
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)

class HSBetModule(BaseModule):

    ID = __name__.split('.')[-1]
    NAME = 'Hearthstone Betting'
    DESCRIPTION = 'Enables betting on Hearthstone game outcomes with !hsbet'
    SETTINGS = [
            ModuleSetting(
                key='trackobot_username',
                label='Track-o-bot Username',
                type='text',
                required=True,
                placeholder='Username',
                default='',
                constraints={
                    'min_str_len': 2,
                    'max_str_len': 32,
                    }),
            ModuleSetting(
                key='trackobot_api_key',
                label='Track-o-bot API Key',
                type='text',
                required=True,
                placeholder='API Key',
                default='',
                constraints={
                    'min_str_len': 2,
                    'max_str_len': 32,
                    }),
            ModuleSetting(
                key='time_until_bet_closes',
                label='Seconds until betting closes',
                type='number',
                required=True,
                placeholder='Seconds until betting closes',
                default=120),
            ]

    def __init__(self):
        super().__init__()
        self.bets = {}

        self.last_game_start = None
        self.last_game_id = None

        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.job = self.scheduler.add_job(self.poll_trackobot, 'interval', seconds=15)
        self.job.pause()

    def poll_trackobot(self):
        url = 'https://trackobot.com/profile/history.json?username={username}&token={api_key}'.format(
                username=self.settings['trackobot_username'],
                api_key=self.settings['trackobot_api_key'])
        r = requests.get(url)
        game_data = r.json()
        if 'history' not in game_data:
            log.error('Invalid json?')
            return False

        if len(game_data['history']) == 0:
            log.error('No games found in the history.')
            return False

        latest_game = game_data['history'][0]

        if latest_game['id'] != self.last_game_id:
            for username in self.bets:
                bet_for_win, points = self.bets[username]
                """
                self.bot.say('{} bet {} points on the last game to end up as a {}'.format(
                    username,
                    points,
                    'win' if bet_for_win else 'loss'))
                    """

                user = self.bot.users[username]

                correct_bet = (latest_game['result'] == 'win' and bet_for_win is True) or (latest_game['result'] == 'loss' and bet_for_win is False)
                if correct_bet:
                    user.points += points
                    user.remove_debt(points)
                    self.bot.say('{} won {} points by correctly betting on the hs game!'.format(user.username_raw, points))
                    HandlerManager.trigger('on_user_win_hs_bet', user, points)
                else:
                    user.pay_debt(points)
                    log.debug('{} lost {} points!'.format())

            self.bot.say('A new game has begun! Vote with !hsbet win/lose POINTS')
            self.bets = {}
            self.last_game_id = latest_game['id']
            self.last_game_start = datetime.datetime.now()

    def hsbet_command(self, **options):
        bot = options['bot']
        source = options['source']
        message = options['message']

        if message is None:
            return False

        if self.last_game_start is None:
            return False

        time_delta = datetime.datetime.now() - self.last_game_start

        if time_delta.total_seconds() > self.settings['time_until_bet_closes']:
            bot.whisper(source.username, 'The game is too far along for you to bet on it. Wait until the next game!')
            return False

        msg_parts = message.split(' ')
        if msg_parts == 0:
            bot.whisper(source.username, 'Usage: !hsbet win/loss POINTS')
            return False

        outcome = msg_parts[0].lower()
        bet_for_win = False

        if outcome in ('win', 'winner'):
            bet_for_win = True
        elif outcome in ('lose', 'loss', 'loser'):
            bet_for_win = False
        else:
            bot.whisper(source.username, 'Invalid bet. Usage: !hsbet win/loss POINTS')
            return False

        points = 0
        try:
            points = int(msg_parts[1])
        except (IndexError, ValueError, TypeError):
            pass

        if not source.can_afford(points):
            bot.whisper(source.username, 'You don\'t have {} points to bet'.format(points))
            return False

        if source.username in self.bets:
            bot.whisper(source.username, 'You have already bet on this game. Wait until the next game starts!')
            return False

        source.create_debt(points)
        self.bets[source.username] = (bet_for_win, points)
        bot.whisper(source.username, 'You have bet {} points on this game resulting in a {}.'.format(points, 'win' if bet_for_win else 'loss'))

    def load_commands(self, **options):
        self.commands['hsbet'] = Command.raw_command(
                self.hsbet_command,
                delay_all=0,
                delay_user=10,
                )

    def enable(self, bot):
        self.job.resume()
        self.bot = bot

    def disable(self, bot):
        self.job.pause()