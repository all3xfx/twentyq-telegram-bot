#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Basic example for a bot that awaits an answer from the user. It's built upon
# the state_machine_bot.py example
# This program is dedicated to the public domain under the CC0 license.

import os
import pickle
import logging
import requests
import postgresql
from bs4 import BeautifulSoup
from telegram import Emoji, ForceReply, InlineKeyboardButton, \
    InlineKeyboardMarkup, ParseMode, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, \
    CallbackQueryHandler, Filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - '
                           '%(message)s',
                    level=logging.DEBUG)

# Set some defaults
TWENTY_QUESTIONS_HOME_URL = "http://www.20q.net"
TWENTY_QUESTIONS_DATA_URL = "http://y.20q.net"
TWENTY_QUESTIONS_LOC = "/gsq-enUK"

ADMIN_USER_NAME = '@zachd'
AVAILABLE_OPTIONS = ['Yes','No','Unknown',
                    'Irrelevant','Sometimes','Partly',
                    'Right', 'Wrong', 'Close']

# Load file from disk
state = {}
if os.path.isfile('state.pkl'):
    pkl_file = open('state.pkl', 'rb')
    state = pickle.load(pkl_file)
    pkl_file.close()
    logging.info("Loaded state from pickle file.")

def answer_q(bot, update):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    message_id = query.message.message_id

    if query.data == '?':
        answer_callback(bot, query.id, "Confused? Here's how to play.")
        help_text = "*Playing 20Q*\nThink of something and 20Q will read your mind by " \
        "asking a few simple questions. The object you think of should be something " \
        "that most people would know about, but not a proper noun or a specific person, " \
        "place, or thing.\n\nChoose a category in the message above that best describes what you're thinking."
        bot.sendMessage(text=help_text, chat_id=chat_id,
                    parse_mode=ParseMode.MARKDOWN)
        return True

    elif query.data == 'restart':
        answer_callback(bot, query.id, "Great! Let's play again.")
        start_game()
        return True

    elif query.data == 'stats':
        try:
            stats = state[user_id]['stats']
            answer_callback(bot, query.id, "Alright! Here are your play stats.")
            bot.sendMessage(text="*Stats*:\n" + "20Q Won: " + state[user_id]['stats']['won'] +
                "\n20Q Lost: " + state[user_id]['stats']['lost'], chat_id=chat_id,
                    parse_mode=ParseMode.MARKDOWN)
        except KeyError:
            stats = 'No stats available!'
            answer_callback(bot, query.id, "Sorry! No stats available.")
        return True

    elif query.data == 'hints':
        try:
            hints = state[user_id]['hints']
            answer_callback(bot, query.id, "Alright! Here are hints from our last game.")
            bot.sendMessage(text="*Hints*:\n" + hints, chat_id=chat_id,
                    parse_mode=ParseMode.MARKDOWN)
        except KeyError:
            answer_callback(bot, query.id, "Sorry! No hints available.")
        return True

    else:
        # Modify previous message
        bot.editMessageText(text=query.message.text + "\nYou answered: _" + query.data + "_", 
            message_id=message_id, chat_id=chat_id, parse_mode=ParseMode.MARKDOWN,
            reply_markup=None)

        # Get data from state dict
        try:
            data = state[user_id]['resp'][query.data]
        except KeyError:
            # Send message stating game has ended
            answer_callback(bot, query.id, "Oops! This game has ended.")
            bot.sendMessage(text="Sorry, this game has ended. Please type */start*.",
                chat_id=chat_id, parse_mode=ParseMode.MARKDOWN)
            return True

        # Start next question
        headers = {'Referer': TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC}
        resp = requests.get(TWENTY_QUESTIONS_DATA_URL + TWENTY_QUESTIONS_LOC + '?' 
                                + data, headers=headers)
        soup = BeautifulSoup(resp.content, 'html.parser')

        h2s = soup.find_all('h2')
        if h2s:
            state[user_id] = {}
            custom_keyboard = [[InlineKeyboardButton('Sure!', callback_data='restart'),
                                InlineKeyboardButton('See Stats', callback_data='stats'),
                                InlineKeyboardButton('See Hints', callback_data='hints') 
                                ]]
            try:
                raw_hints = soup.find('td').text.split('\n')[6].split('.')[:-5]
                hints = '\n'.join(raw_hints)
            except:
                hints = 'No hints available!'
            state[user_id]['hints'] = hints

            reply_markup = InlineKeyboardMarkup(custom_keyboard)
            if h2s[0].string == "20Q won!":
                state[user_id]['stats']['won'] += 1
                bot.sendMessage(text="20Q won! Play again?",
                            reply_markup=reply_markup, chat_id=chat_id)
            else:
                state[user_id]['stats']['lost'] += 1
                bot.sendMessage(text="20Q lost. Play again?",
                            reply_markup=reply_markup, chat_id=chat_id)
        else:

            # Sort through options
            custom_keyboard = [[],[]]
            row_number = 0

            state[user_id]['resp'] = {}
            question = soup.big.b.text.split('\n')[0].replace('\xa0', '')
            options = soup.big.find_all('a')

            if len(options) != 12 and len(options) != 3:
                import pdb; pdb.set_trace()

            for option in options:
                choice = option.string.replace('\xa0', '').replace(' ', '')
                if choice in AVAILABLE_OPTIONS:
                    state[user_id]['resp'][choice] = option['href'].split('?')[1]
                    button = InlineKeyboardButton(choice, callback_data=choice)
                    if len(custom_keyboard[row_number]) == 3:
                        row_number += 1
                    custom_keyboard[row_number].append(button)

            # Send callback answer popup message
            answer_callback(bot, query.id, "Alright! Next Question.")

            # Reply to user
            reply_markup = InlineKeyboardMarkup(custom_keyboard)
            bot.sendMessage(text=question, reply_markup=reply_markup, chat_id=chat_id,
                        parse_mode=ParseMode.MARKDOWN)
        
def start_game(bot, update):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    # Create new user state
    if user_id not in state:
        state[user_id] = {'hints': '', 'resp': {}, 'stats': {'won': 0, 'lost': 0}}

    # Send the typing action
    bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)

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
    custom_keyboard = [[], []]
    row_number = 0
    state[user_id]['resp'] = {}
    options = soup.find_all('a', {'target': 'mainFrame'})

    for option in options:
        choice = option.string.replace('\xa0', '')
        state[user_id]['resp'][choice] = option['href'].split('?')[1]
        if len(custom_keyboard[row_number]) == 3:
            row_number += 1
        custom_keyboard[row_number].append(InlineKeyboardButton(choice,
            callback_data=choice))

    # Reply to user
    reply_markup = InlineKeyboardMarkup(custom_keyboard)
    bot.sendMessage(text="*20Q can read you mind.* Let's go!\n" \
                    "Q1. Is it classified as Animal, Vegetable or Mineral?",
                    reply_markup=reply_markup, chat_id=chat_id,
                    parse_mode=ParseMode.MARKDOWN)

def answer_callback(bot, query_id, text):
    bot.answerCallbackQuery(query_id, text=text)

def help(bot, update):
    bot.sendMessage(update.message.chat_id, text="Type */start* to begin playing.",
     parse_mode=ParseMode.MARKDOWN)

def error(bot, update, error):
    logging.warning('Update "%s" caused error "%s"' % (update, error))

def admin_pdb(bot, update):
    if update.message.from_user.name == ADMIN_USER_NAME:
        import pdb; pdb.set_trace()

def admin_exit(bot, update):
    if update.message.from_user.name == ADMIN_USER_NAME:
        output = open('state.pkl', 'wb')
        pickle.dump(state, output)
        output.close()
        logging.info("Saved state to pickle file.")
        updater.stop()

# Create the Updater and pass it your bot's token.
updater = Updater("BOT_TOKEN_HERE")

# The confirmation
updater.dispatcher.addHandler(CallbackQueryHandler(answer_q))
updater.dispatcher.addHandler(CommandHandler('pdb', admin_pdb))
updater.dispatcher.addHandler(CommandHandler('exit', admin_exit))
updater.dispatcher.addHandler(CommandHandler('start', start_game))
updater.dispatcher.addHandler(CommandHandler('help', help))
updater.dispatcher.addErrorHandler(error)

# Start the Bot
updater.start_polling()

# Run the bot until the user presses Ctrl-C or the process receives SIGINT,
# SIGTERM or SIGABRT
updater.idle()