#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import logging
import requests
import postgresql
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, \
    Emoji, ParseMode, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, \
    CallbackQueryHandler, Filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - '
                           '%(message)s',
                    level=logging.INFO)

# Open connection to PostgreSQL database
db = postgresql.open("pq://USER:PASS@HOST/DATABASE")

# Define some prepared SQL statements
get_user = db.prepare("SELECT * FROM users WHERE user_id=$1")
update_stats = db.prepare("UPDATE users SET wins=$2, losses=$3, hints=$4 WHERE user_id=$1")
update_options = db.prepare("UPDATE users SET options=$2, messages=$3 WHERE user_id=$1")
create_user = db.prepare("INSERT INTO users (user_id, user_name) VALUES (CAST($1 AS INT), $2)")

# Set some defaults
TWENTY_QUESTIONS_HOME_URL = "http://www.20q.net"
TWENTY_QUESTIONS_DATA_URL = "http://y.20q.net"
TWENTY_QUESTIONS_LOC = "/gsq-enUK"
ADMIN_USER_NAME = '@zachd'
VALID_OPTION = re.compile("^[\w\?]+$")
VALID_LANGUAGES = [('English (US)', 'us'), ('English (UK)', 'gb'), ('English (CA)', 'ca'),
('Deutsch', 'de'), ('Français', 'fr'), ('Español', 'es'), ('Italiano', 'en'), ('國語', 'zh'),
('廣東話', 'zhgb'), ('Nederlands', 'nl'), ('日本語', 'jp'), ('Dansk', 'dk'), ('Magyar', 'hu'),
('Čeština', 'cs'), ('Ελληνικά', 'el'), ('Svenska', 'se'), ('Polski', 'pl'), ('Português', 'pt'),
('한국어', 'ko'), ('Suomi', 'fi'), ('Türkçe', 'tr'), ('Norsk', 'no')]

#Answer question function
def answer_q(bot, update):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    current_user = get_user.first(user_id)

    # User independant callback actions
    if query.data in ['?', 'help']:
        answer_callback(bot, query.id, "Confused? Here's how to play.")
        help_text = "*Playing 20Q*\nThink of something and 20Q will read your mind by " \
        "asking a few simple questions. The object you think of should be something " \
        "that most people would know about, but not a proper noun or a specific person, " \
        "place, or thing.\n\nChoose a category in the message above that best describes what you're thinking."
        send_message(bot, help_text, chat_id)
        return True

    elif query.data in ['start', 'Play Again']:
        answer_callback(bot, query.id, "Great! Let's play" + 
            (" again." if query.data == 'Play Again' else "."))
        start_game(bot, query, True)
        return True

    # Check if the request came from a valid user
    if not current_user:
        return error(bot, query, "Invalid User", True)

    # User dependant callback actions
    if query.data == 'stats':
        answer_callback(bot, query.id, "Alright! Here are your play stats.")
        stats(bot, query, current_user)

    elif query.data == 'hints':
        answer_callback(bot, query.id, "Alright! Here are hints from your last game.")
        hints(bot, query, current_user)

    elif VALID_OPTION.match(query.data):

        # Modify previous message
        bot.editMessageText(text=query.message.text + "\nYou answered: _" + query.data + "_", 
            message_id=query.message.message_id, chat_id=chat_id, parse_mode=ParseMode.MARKDOWN,
            reply_markup=None)

        # Get action from options list in database
        options_list = current_user['options'].nest()
        action = next(action for [choice, action] in options_list if choice == query.data)

        # Get result of selected action
        headers = {'Referer': TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC}
        resp = requests.get(TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC + '?' 
                                + action, headers=headers)
        soup = BeautifulSoup(resp.content, 'html.parser')

        # Check if the game is over
        h2s = soup.find_all('h2')
        if h2s:
            # Get hints section
            try:
                raw_hints = soup.find('td').text.split('\n')[6].split('.')[:-5]
                hints_str = '\n'.join(raw_hints)
            except:
                hints_str = 'No hints available!'

            # Create response keyboard
            keyboard_buttons = [[InlineKeyboardButton('Play Again', callback_data='Play Again'),
                                InlineKeyboardButton('Visit 20Q', url='http://20q.net')],
                               [InlineKeyboardButton('Show Stats', callback_data='stats'),
                                InlineKeyboardButton('Show Hints', callback_data='hints')]]
            custom_keyboard = InlineKeyboardMarkup(keyboard_buttons)

            # Send message dependant on result
            if h2s[0].string == "20Q won!":
                send_message(bot, "*" + h2s[0].string + "*", chat_id, custom_keyboard)
                update_stats(user_id, current_user['wins'] + 1, current_user['losses'], hints_str)
            elif h2s[0].string == "You won!":
                if soup.big.string == 'Is it one of these ...':
                    options = soup.tr.find_all('a')
                    custom_keyboard = get_custom_keyboard(user_id, current_user, ab)
                    send_message(bot, h2s[0].string + " " + soup.big.string, chat_id, custom_keyboard)
                else:
                    send_message(bot, "*" + h2s[0].string + "*", chat_id, custom_keyboard)
                update_stats(user_id, current_user['wins'] + 1, current_user['losses'], hints_str)
            else:
                send_message(bot, "*" + h2s[0].string + "*", chat_id, custom_keyboard)
                update_stats(user_id, current_user['wins'], current_user['losses'] + 1, hints_str)

        # Otherwise, send the next question
        else:
            options = soup.big.find_all('a')
            question = soup.big.b.text.split('\n')[0].replace('\xa0', '')
            custom_keyboard = get_custom_keyboard(user_id, current_user, options)

            # Send callback popup and reply message
            answer_callback(bot, query.id, "Alright! Next Question.")
            send_message(bot, question, chat_id, custom_keyboard)
    else:
        answer_callback(bot, query.id, "An error occured.")
        send_message(bot, "An error occured.", chat_id)


# Start game function
def start_game(bot, update, restart=False):
    chat_id = update.message.chat_id
    user = update.from_user if restart else update.message.from_user

    # Send the typing action
    bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)

    # Get user state from database
    current_user = get_user.first(user.id)
    if not current_user:
        create_user(user.id, user.name)

    # Get start game singup page
    headers = {'Referer': TWENTY_QUESTIONS_HOME_URL + '/play.html'}
    resp = requests.get(TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC, headers=headers)
    soup = BeautifulSoup(resp.content, 'html.parser')
    start_key = soup.form['action']

    # Click Play button on signup page
    headers = {'Referer': TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC}
    form = {
        'age': '',
        'cctkr': 'IE,GB,FR,NL,HU,US,RO,AE',
        'submit': 'Play'
    }
    resp = requests.post(TWENTY_QUESTIONS_DATA_URL + start_key, data=form, headers=headers)
    soup = BeautifulSoup(resp.content, 'html.parser')

    # Sort through options
    options = soup.find_all('a', {'target': 'mainFrame'})
    custom_keyboard = get_custom_keyboard(user.id, current_user, options)

    # Reply to user
    send_message(bot, "*20Q can read you mind.* Let's go!\n\n" \
                    "Q1. Is it classified as Animal, Vegetable or Mineral?",
                    chat_id, custom_keyboard)


# Helper Functions
def get_custom_keyboard(user_id, user, options):
    custom_keyboard = [[], []]
    options_list = []
    row_number = 0

    for option in options:
        choice = option.string.replace('\xa0', '').replace(' ', '')
        action = option['href'].split('?')[1]
        if len(custom_keyboard[row_number]) == 3:
            row_number += 1
        options_list.append([choice, action])
        custom_keyboard[row_number].append(InlineKeyboardButton(choice,
            callback_data=choice))
    update_options(user_id, options_list, (user['messages'] + 1 if user else 1))
    return InlineKeyboardMarkup(custom_keyboard)

def answer_callback(bot, query_id, text):
    bot.answerCallbackQuery(query_id, text=text)

def send_message(bot, text, chat_id, reply_markup=None):
    bot.sendMessage(text=text, chat_id=chat_id, reply_markup=reply_markup, 
                    parse_mode=ParseMode.MARKDOWN)


# Command Handlers
def stats(bot, update, user=None):
    user = user or get_user.first(update.message.from_user.id)
    total = user['wins'] + user['losses']
    send_message(bot, "*Play Stats*:\n20Q Won: *" + str(user['wins']) + "*\n20Q Lost: *"
         + str(user['losses']) + "*\nTotal games: *" + str((1 if total == 0 else total))
         + "*\nAvg Qs/game: *" + str(int(user['messages'] / (1 if total == 0 else total)))
         + "*", update.message.chat_id)

def hints(bot, update, user=None, reply_markup=None):
    user = user or get_user.first(update.message.from_user.id)
    user_hints = "*Game Hints*:\n" + ("No hints available." if user['hints'] is None else user['hints'])
    if user is None or user['hints'] is None:
        user_hints = "You have no hints available. Have you played a game yet?"
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton('Start Playing', callback_data='start')],
            [InlineKeyboardButton('How to Play', callback_data='help')]
        ])
    send_message(bot, user_hints, update.message.chat_id, reply_markup)

def help(bot, update):
    bot.sendMessage(update.message.chat_id, text="Type */start* to begin playing.",
     parse_mode=ParseMode.MARKDOWN)

def error(bot, update, error, show_error=False):
    logging.warning('Update "%s" caused error "%s"' % (update, error))
    if show_error:
        answer_callback(bot, query.id, "Oops! This game has ended.")
        send_message(bot, "Sorry, this game has ended. Please type */start*.", chat_id)
    return True

def admin_pdb(bot, update):
    if update.message.from_user.name == ADMIN_USER_NAME:
        import pdb; pdb.set_trace()

def admin_exit(bot, update):
    if update.message.from_user.name == ADMIN_USER_NAME:
        updater.stop()


# Create the Updater and pass it your bot's token.
updater = Updater("BOT_TOKEN_HERE")

# Register handler functions
updater.dispatcher.addHandler(CallbackQueryHandler(answer_q))
updater.dispatcher.addHandler(CommandHandler('pdb', admin_pdb))
updater.dispatcher.addHandler(CommandHandler('exit', admin_exit))
updater.dispatcher.addHandler(CommandHandler('start', start_game))
updater.dispatcher.addHandler(CommandHandler('stats', stats))
updater.dispatcher.addHandler(CommandHandler('hints', hints))
updater.dispatcher.addHandler(CommandHandler('help', help))
updater.dispatcher.addErrorHandler(error)

# Start the Bot
updater.start_polling()

# Run the bot until the user presses Ctrl-C or the 
# process receives SIGINT, SIGTERM or SIGABRT
updater.idle()
