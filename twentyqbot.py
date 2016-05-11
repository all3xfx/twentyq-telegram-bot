#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import logging
import requests
import postgresql
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, \
    Emoji, ParseMode, ChatAction, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, \
    CallbackQueryHandler, Filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - '
                           '%(message)s',
                    level=logging.INFO)

# Open connection to PostgreSQL database
db = postgresql.open("pq://USER:PASS@HOST/DATABASE")

# Define some prepared SQL statements
get_user = db.prepare("SELECT * FROM users WHERE user_id=$1")
set_lang_game = db.prepare("UPDATE users SET language=$2, gametype=$3 WHERE user_id=$1")
update_stats = db.prepare("UPDATE users SET wins=$2, losses=$3, hints=$4, answer=$5, question=NULL WHERE user_id=$1")
update_options = db.prepare("UPDATE users SET question=$2, options=$3, messages=$4 WHERE user_id=$1")
create_user = db.prepare("INSERT INTO users (user_id, user_name) VALUES (CAST($1 AS INT), $2)")

# Set some defaults
TWENTY_QUESTIONS_URL = "20q.net"
UNICODE_OFFSET = ord('🇦') - ord('A')
VALID_OPTION = re.compile("^[\w\?\s]+$")
ADMIN_USER_NAME = '@zachd'
BUTTONS_PER_ROW = 3

# Set valid gametypes
DEFAULT_GAMETYPE = 'y'
VALID_GAMETYPES = [('Classic', 'y'), ('Star Wars', 'starwars'), ('Disney', 'disney'), ('The Simpsons', 'thomp'),
('Star Trek', 'trek'), ('Doctor Who', 'what'), ('20Q Earth', 'place'), ('20Q Movies', 'movies'), ('20Q TV', 'tv'),
('20Q People', 'people'), ('20Q Sports', 'sports'), ('20Q Music', 'music'), ('20Q Name Game', 'names')]

# Set valid languages
DEFAULT_LANGUAGE = 'en'
VALID_LANGUAGES = [('English (US)', 'US', 'en'), ('English (UK)', 'GB', 'enUK'), ('English (CA)', 'CA', 'enCA'),
('Français', 'FR', 'fr'), ('Deutsch', 'DE', 'de'), ('Español', 'ES', 'es'), ('Italiano', 'IT', 'it'), ('Nederlands', 'NL', 'nl'), 
('Português', 'PT', 'pt'), ('Dansk', 'DK', 'dk'), ('Polski', 'PL', 'pl'), ('Norsk', 'NO', 'no'), ('Svenska', 'SE', 'se'), 
('Čeština', 'CZ', 'cs'), ('Ελληνικά', 'GR', 'el'), ('Türkçe', 'TR', 'tr'), ('Magyar', 'HU', 'hu'), ('Suomi', 'FI', 'fi'), 
('國語', 'CN', 'zh'), ('廣東話', 'CN', 'zhgb'), ('日本語', 'JP', 'jp'), ('한국어', 'KR', 'ko')]

#Answer question function
def answer_q(bot, update):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    current_user = get_user.first(user_id)

    # Check if the request came from a valid user
    if not current_user:
        return error(bot, query, "An error occured. Try /start?", from_query=True)

    # User independant callback actions
    if query.data == '?':
        answer_callback(bot, query.id, "Need some help?")
        cmd_help(bot, query, current_user)

    elif query.data in ['start', 'Play Again']:
        answer_callback(bot, query.id, "Great! Let's play" + 
            (" again." if query.data == 'Play Again' else "."))
        cmd_start(bot, query, from_query=True)

    elif query.data == 'stats':
        answer_callback(bot, query.id, "Alright! Here are your play stats.")
        cmd_stats(bot, query, current_user)

    elif query.data == 'hints':
        answer_callback(bot, query.id, "Alright! Here are hints from your last game.")
        cmd_hints(bot, query, current_user)

    elif query.data == 'language':
        answer_callback(bot, query.id, "Alright! Select a new language below.")
        cmd_language(bot, query, current_user)

    elif query.data == 'gametype':
        answer_callback(bot, query.id, "Alright! Select a new game type below.")
        cmd_gametype(bot, query, current_user)

    elif VALID_OPTION.match(query.data):

        (gametype, _, language) = get_game_lang(current_user)

        # Modify previous message
        bot.editMessageText(text=query.message.text + "\nYou answered: _" + query.data + "_", 
            message_id=query.message.message_id, chat_id=chat_id, parse_mode=ParseMode.MARKDOWN,
            reply_markup=None)

        # Get action from options list in database
        options_list = current_user['options'].nest()
        try:
            action = next(action for [choice, action] in options_list if choice == query.data)
        except StopIteration:
            return error(bot, query, "This game has ended.", from_query=True)

        # Get result of selected action
        headers = {'Referer': 'http://' + gametype + '.' + TWENTY_QUESTIONS_URL + language}
        resp = requests.get('http://' + gametype + '.' + TWENTY_QUESTIONS_URL + language + '?' 
                                + action, headers=headers)
        soup = BeautifulSoup(resp.content, 'html.parser')

        # Check if the game is over
        h2s = soup.find_all('h2')
        if h2s:

            # Get hints section
            try:
                raw_hints = soup.find('td').text.split('\n')[6].split('.')[:-5]
                hints = '\n'.join(raw_hints)
            except:
                hints = 'No hints available!'

            # Create response keyboard
            keyboard_buttons = [[InlineKeyboardButton('Play Again', callback_data='Play Again'),
                                InlineKeyboardButton('Visit 20Q', url='http://20q.net')],
                               [InlineKeyboardButton('Show Stats', callback_data='stats'),
                                InlineKeyboardButton('Show Hints', callback_data='hints')]]
            custom_keyboard = InlineKeyboardMarkup(keyboard_buttons)

            first_answer = action == options_list[0][1]
            if current_user['question']:
                question_num = int(current_user['question'][1:3].replace('.', ''))

            # If 20Q was right in less than 20 questions
            if first_answer and question_num and question_num <= 20:
                send_message(bot, "*" + h2s[0].string + "*", chat_id, custom_keyboard)
                update_stats(user_id, current_user['wins'] + 1, current_user['losses'], hints, soup.big.string)
            else:
                answer = None
                inputs = soup.find_all('input')
                if inputs:
                    options = soup.tr.find_all('a')
                    custom_keyboard = get_custom_keyboard(user_id, current_user, options)
                    send_message(bot, "*" + h2s[0].string + "* " + soup.big.string, chat_id, custom_keyboard)
                else:
                    answer = soup.big.string
                    send_message(bot, "*" + h2s[0].string + "*", chat_id, custom_keyboard)
                if current_user['question']:
                    update_stats(user_id, current_user['wins'], current_user['losses'] + 1, hints, answer)

        # Otherwise, send the next question
        else:
            options = soup.big.find_all('a')
            question = clean_input(soup.big.text.split('\n')[0])
            custom_keyboard = get_custom_keyboard(user_id, current_user, options, question)

            # Send callback popup and reply message
            answer_callback(bot, query.id, "Alright! Next Question.")
            send_message(bot, question, chat_id, custom_keyboard)
    else:
        answer_callback(bot, query.id, "An error occured.")
        return error(bot, query, "Invalid option.")


# Start game function
def cmd_start(bot, update, from_query=False, restart=False):
    chat_id = update.message.chat_id
    user = update.from_user if from_query else update.message.from_user

    # Send the typing action
    bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)

    # Get user state from database
    current_user = get_user.first(user.id)
    if not current_user:
        create_user(user.id, user.name)

    if current_user and current_user['question'] and not restart:
        previous = [InlineKeyboardButton(opt, callback_data=opt) \
            for [opt, action] in current_user['options'].nest()]
        custom_keyboard = [previous[i:i+BUTTONS_PER_ROW] for i in range(0, len(previous), BUTTONS_PER_ROW)]
        send_message(bot, "You're already playing a game! Wanna /restart?\n\n"
             + current_user['question'], chat_id, InlineKeyboardMarkup(custom_keyboard))
        return True

    start_page = get_start_page(bot, current_user, chat_id)

    # Sort through options
    options = start_page.find_all('a', {'target': 'mainFrame'})
    intro_text = clean_input(start_page.table.p.big.text.replace('A.I.', 'AI').replace('. ', '.*\n', 1))
    question = clean_input(start_page.table.td.td.find_all('big', recursive=False)[0].text.split('\n')[0])
    custom_keyboard = get_custom_keyboard(user.id, current_user, options, question)

    # Reply to user
    send_message(bot, "*" + intro_text + "\n\n" + question, chat_id, custom_keyboard)


# Helper Functions
def get_custom_keyboard(user_id, user, options, question=None, just_options=False):
    custom_keyboard = [[]]
    options_list = []
    row_num = 2 if len(options) == 5 else BUTTONS_PER_ROW
    row_number = 0

    for opt in options:
        choice = clean_input(opt.string)
        action = opt['href'].split('?')[1]

        # Special case to remove "Probably", "Doubtful", and "Usually" (unnecessary)
        if not (question and options.index(opt) >= 7 and options.index(opt) <= 9) \
                and not (row_num == 2 and choice == '?'):
            if len(custom_keyboard[row_number]) == row_num:
                row_number += 1
                custom_keyboard.append([])
            options_list.append([choice, action])
            custom_keyboard[row_number].append(InlineKeyboardButton(choice,
                callback_data=choice))

    update_options(user_id, question, options_list, (user['messages'] + 1 if user else 1))
    return InlineKeyboardMarkup(custom_keyboard)

def get_start_page(bot, user, chat_id):
    (gametype, _, language) = get_game_lang(user)
    data_url = 'http://' + gametype + '.' + TWENTY_QUESTIONS_URL

    # Request signup page for selected game
    headers = {'Referer': 'http://' + TWENTY_QUESTIONS_URL + '/play.html'}
    resp = requests.get(data_url + language, headers=headers)
    soup = BeautifulSoup(resp.content, 'html.parser')
    start_key = soup.form['action']

    # Click Play button on signup page
    headers = {'Referer': data_url + language}
    form = {'submit': 'Play'}
    resp = requests.post(data_url + start_key, data=form, headers=headers)

    # Send an image for selected game types
    if gametype in ['starwars', 'trek', 'thomp', 'disney', 'what']:
        bot.sendChatAction(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        bot.sendPhoto(chat_id=chat_id, photo=open('assets/' + gametype + '.png', 'rb'))

    return BeautifulSoup(resp.content, 'html.parser')

def get_game_lang(user):
    game = user['gametype'] if user and user['gametype'] else DEFAULT_GAMETYPE
    lang = user['language'] if user and user['language'] else DEFAULT_LANGUAGE
    full_lang = '/gsq-' + lang if game == DEFAULT_GAMETYPE else '/gse'
    return (game, lang, full_lang)

def get_unicode_flag(code):
    # http://schinckel.net/2015/10/29/unicode-flags-in-python/
    return chr(ord(code[0]) + UNICODE_OFFSET) + chr(ord(code[1]) + UNICODE_OFFSET)

def clean_input(input):
    return input.replace('\xa0', '').strip()

def answer_callback(bot, query_id, text):
    bot.answerCallbackQuery(query_id, text=text)

def send_message(bot, text, chat_id, reply_markup=None):
    bot.sendMessage(text=text, chat_id=chat_id, reply_markup=reply_markup, 
                    parse_mode=ParseMode.MARKDOWN)

# Command Handlers
def message(bot, update):
    user = update.message.from_user
    updated = False
    current_user = get_user.first(user.id)
    (gametype, language, _) = get_game_lang(current_user)
    for (lang, code, url) in VALID_LANGUAGES:
        if lang == update.message.text[3:]:
            language = url
            updated = True
            send_message(bot, "Language changed to " + get_unicode_flag(code) + " " + \
                lang + ".", update.message.chat_id)
    for (game, code) in VALID_GAMETYPES:
        if game.lower() == update.message.text.lower():
            gametype = code
            updated = True
            send_message(bot, "Gametype changed to " + game + ".", update.message.chat_id)
    if updated:
        set_lang_game(user.id, language, gametype)
        cmd_restart(bot, update)
    else:
        bot.sendChatAction(chat_id=update.message.chat_id, action=ChatAction.UPLOAD_VIDEO)
        send_message(bot, "*Unknown game type.*\nLooking to play 20Q? Type /start.", update.message.chat_id)
        bot.sendVideo(chat_id=update.message.chat_id, video=open('assets/20q.mp4', 'rb'))

def cmd_stats(bot, update, user=None, custom_keyboard=None):
    user = user or get_user.first(update.message.from_user.id)
    total = 0 if not user else user['wins'] + user['losses']
    if user is None or total == 0:
        user_stats = "You have no stats available. Have you played a game yet?"
        custom_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('Start Playing', callback_data='start'),
            InlineKeyboardButton('How to Play', callback_data='?')]
        ])
    else:
        user_stats = "*Play Stats*:\n20Q Won: *" + str(user['wins']) + "*\n20Q Lost: *" + \
            str(user['losses']) + "*\nTotal games: *" + str(total) + "*\nAvg Qs/game: *" + \
            str(int(user['messages'] / (1 if total == 0 else total))) + "*"
    send_message(bot, user_stats, update.message.chat_id, custom_keyboard)

def cmd_hints(bot, update, user=None, custom_keyboard=None):
    user = user or get_user.first(update.message.from_user.id)
    if user is None or not user['hints']:
        user_hints = "You have no hints available. Have you played a game yet?"
        custom_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('Start Playing', callback_data='start'),
            InlineKeyboardButton('How to Play', callback_data='?')]
        ])
    else:
        user_hints = "*Answer*: " + user['answer'] + "\n*Hints*: " + user['hints']
    send_message(bot, user_hints, update.message.chat_id, custom_keyboard)

def cmd_restart(bot, update):
    user_id = update.message.from_user.id
    user = get_user.first(user_id)
    if user and user['question']:
        question_num = int(user['question'][1:3].replace('.', ''))
        update_options(user_id, None, None, user['messages'] - question_num)
    cmd_start(bot, update, restart=True)

def cmd_help(bot, update, user=None, custom_keyboard=None):
    user = user or get_user.first(update.message.from_user.id)
    start_page = get_start_page(bot, user, update.message.chat_id)
    help_text = "*20Q can read you mind!*\n" + clean_input(start_page.find_all('big')[0].text) + \
        "\n" + clean_input(start_page.find_all('p')[1].text) + " _" + \
        clean_input(start_page.find_all('br')[3].text) + "_"
    custom_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Change Language", callback_data='language'),
        InlineKeyboardButton("Change Game Type", callback_data='gametype')
    ]])
    send_message(bot, help_text, update.message.chat_id, custom_keyboard)

def cmd_language(bot, update, user=None):
    user = user or get_user.first(update.message.from_user.id)
    user_lang = user['language'] if user and user['language'] else DEFAULT_LANGUAGE
    (lang_full, country_code) = next((l, c) for (l, c, u) in VALID_LANGUAGES if u == user_lang)
    language_buttons = [KeyboardButton(get_unicode_flag(c) + " " + l) for (l, c, p) in VALID_LANGUAGES]
    custom_keyboard = [language_buttons[i:i+2] for i in range(0, len(language_buttons), 2)]
    send_message(bot, "Current: " + get_unicode_flag(country_code) + " " + lang_full + "\nSelect a language.", \
        update.message.chat_id, ReplyKeyboardMarkup(custom_keyboard, one_time_keyboard=True))
    return True

def cmd_gametype(bot, update, user=None):
    user = user or get_user.first(update.message.from_user.id)
    user_gametype = user['gametype'] if user and user['gametype'] else DEFAULT_GAMETYPE
    (gametype, game_code) = next((g, c) for (g, c) in VALID_GAMETYPES if c == user_gametype)
    gametype_buttons = [KeyboardButton(g) for (g, c) in VALID_GAMETYPES]
    custom_keyboard = [gametype_buttons[i:i+2] for i in range(1, len(gametype_buttons), 2)]
    custom_keyboard.insert(0, [gametype_buttons[0]])
    send_message(bot, "Current: *" + gametype + "*\nSelect a gametype.", \
        update.message.chat_id, ReplyKeyboardMarkup(custom_keyboard, one_time_keyboard=True))
    return True

def error(bot, update, error_text="Something went wrong!", from_query=True):
    logging.warning('Update "%s" caused error "%s"' % (update, error))
    if from_query:
        answer_callback(bot, update.id, "Oops! An error occured.")
    send_message(bot, "*Error*: " + error_text, update.message.chat_id)
    return True

# Create the Updater and pass it your bot's token.
updater = Updater("BOT_TOKEN_HERE")

# Register handler functions
updater.dispatcher.addHandler(CallbackQueryHandler(answer_q))
updater.dispatcher.addHandler(MessageHandler([Filters.text], message))
updater.dispatcher.addHandler(CommandHandler('start', cmd_start))
updater.dispatcher.addHandler(CommandHandler('restart', cmd_restart))
updater.dispatcher.addHandler(CommandHandler('language', cmd_language))
updater.dispatcher.addHandler(CommandHandler('gametype', cmd_gametype))
updater.dispatcher.addHandler(CommandHandler('stats', cmd_stats))
updater.dispatcher.addHandler(CommandHandler('hints', cmd_hints))
updater.dispatcher.addHandler(CommandHandler('help', cmd_help))
updater.dispatcher.addErrorHandler(error)

# Start the Bot
updater.start_polling()

# Run the bot until the user presses Ctrl-C or the 
# process receives SIGINT, SIGTERM or SIGABRT
updater.idle()
