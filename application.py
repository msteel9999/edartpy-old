import argparse
import datetime
import json
import os
import sys
from collections import deque
from time import sleep

import holidays
import pytz
import requests
from bs4 import BeautifulSoup
from colorama import init
from OpenSSL.SSL import SysCallError

from library import Notify, get_live_price, master_logger
from master import Master

# setup for coloured output
init()

##############################################################

HEADING = '''
                        __           __  ____
              ___  ____/ /___ ______/ /_/ __ \\__  __
             / _ \\/ __  / __ `/ ___/ __/ /_/ / / / /
            /  __/ /_/ / /_/ / /  / /_/ ____/ /_/ /
            \\___/\\__,_/\\__,_/_/   \\__/_/    \\__, /
                                           /____/

'''
Notify.heading(HEADING)

##############################################################

# set time zone
global TZ
TZ = pytz.timezone('Europe/London')
# set holidays
HOLIDAYS = holidays.UnitedStates()
# set market open time
OPEN_TIME = datetime.time(hour=9, minute=15, second=0)
# set market close time
CLOSE_TIME = datetime.time(hour=15, minute=30, second=0)

CHECK_MARKET = False
##############################################################

# only those stocks will be considered whose price is above threshold
PENNY_STOCK_THRESHOLD = 50
# number of stocks to select relevant ones from
NUM_OF_STOCKS_TO_SEARCH = 100
# number of stocks to focus trading on
NUM_OF_STOCKS_TO_FOCUS = 5
# percentage buffer to be set for stop loss/trade exit
global BUFFER_PERCENT
BUFFER_PERCENT = 0.06

# interval of each period, in seconds
global PERIOD_INTERVAL
PERIOD_INTERVAL = 60
# percentage of account_balance to be considered for trading
FEASIBLE_PERCENT = 0.2  # 20%

##############################################################

# time delay to check if market is open, in seconds
DELAY = 300
# delay in idle phase, in seconds
IDLE_DELAY = 0#1800
# time to stop trading
PACK_UP = datetime.time(hour=15, minute=15, second=0)

##############################################################
TODAY = datetime.date.today().strftime("%d-%m-%Y")
if not os.path.exists(f"database/{TODAY}"):
    os.mkdir(f"database/{TODAY}")
master_logger = master_logger(f'database/{TODAY}/master.log')
master_logger.info("-"*76)
master_logger.info("-"*27 + " NEW SESSION DETECTED " + "-"*27)
sys.stderr = open(f"database/{TODAY}/errorStream.txt", "a")

##############################################################

try:
    ACCOUNT = json.loads(open("database/user_info.json").read())["account_balance"] * FEASIBLE_PERCENT
except FileNotFoundError:
    Notify.fatal('User info not found, Aborting.')
    master_logger.critical("User info not found")
    quit(0)
master_logger.info("Successfully loaded user_info.json")
master_logger.info("-"*76)

##############################################################

HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.163 Safari/537.36"
}

##############################################################

parser = argparse.ArgumentParser(prog="application.py",
                                 description="A fully automated Pythonic trading bot\n\nAuthor : Ashwin A Nayar",
                                 epilog="Time for some real money !",
                                 formatter_class=argparse.RawTextHelpFormatter
                                 )

parser.add_argument("--delay", type=int, default=IDLE_DELAY,
                    help="Duration of Idle Phase, in seconds")

parser.add_argument("-nd", action="store_true",
                    help="Skip Idle Phase, not recommended")

parser.add_argument("-np", action="store_true",
                    help="Set period interval to zero, not recommended")

parser.add_argument("-t", action="store_true",
                    help='Run script in trial mode, for debugging purposes')

args = parser.parse_args()

if args.nd:
    if args.delay != IDLE_DELAY:
        Notify.fatal("Invalid set of arguments given. Aborting")
        master_logger.critical("Received no delay and custom delay")
        quit(0)
    else:
        IDLE_DELAY = 0
        master_logger.warning("[  MODE  ]  Zero delay")
else:
    IDLE_DELAY = args.delay
    master_logger.info(f"Idle delay set to {IDLE_DELAY}")

if args.np:
    PERIOD_INTERVAL = 0
    master_logger.warning("[  MODE  ]  Zero period interval")

if args.t:
    IDLE_DELAY = 1
    PERIOD_INTERVAL = 0
    Notify.warn("Running in Test Mode, meant for debugging and demonstration purposes only.")
    master_logger.warning("[  MODE  ]  TEST")
    print("")

# developer mode
DEV_MODE = args.nd and args.np
if DEV_MODE:
    PENNY_STOCK_THRESHOLD = 0
    master_logger.warning("[  MODE  ]  DEVELOPER")

##############################################################

def is_open():
    """
        Function to check if market is open at the moment

    Returns:
        True if market is open, False otherwise

    """
    global ml

    now = datetime.datetime.now(TZ)
    # if a holiday
    if now.strftime('%Y-%m-%d') in HOLIDAYS:
        master_logger.error("Holiday ! ")
        return False
    # if before opening or after closing
    if (now.time() < OPEN_TIME) or (now.time() > CLOSE_TIME):
        master_logger.error("Market closed.")
        return False
    # if it is a weekend
    if now.date().weekday() > 4:
        master_logger.error("Weekday !")
        return False
    return True


def fetch_stocks():
    """
        Find relevant stocks to focus on for trading
    Returns:
        Deque of tickers of relevant stocks

    """

    global ml

    # url to grab data from
    url = f'https://finance.yahoo.com/gainers?count={NUM_OF_STOCKS_TO_SEARCH}'
    # request header
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36'}
    try:
        src = requests.get(url=url, headers=headers).content
    except Exception as e:
        src = None
        Notify.fatal("Trade abort due to unexpected error. Check activity log for details")
        master_logger.critical("Encountered error : ", e)
        quit(0)
    # soup object of source code
    soup = BeautifulSoup(src, "html.parser")
    rows = soup.find('table').tbody.find_all('tr')
    # initialisations
    stocks_temp = dict()
    # check previous day's closing status
    prev_data = json.loads(open("database/user_info.json").read())
    get_sells(stocks_temp, prev_data, "stocks_to_sell")
    get_buys(stocks_temp, prev_data, "stocks_to_buy_back")

    # set counter
    count = len(stocks_temp)
    stocks = deque()
    # iterate over rows in web page
    for tr in rows:
        # exit if
        if count == NUM_OF_STOCKS_TO_FOCUS:
            break
        else:
            row_data = tr.find_all('td')
            ticker = row_data[0].text.strip()
            price = get_live_price(ticker)
            
            
            # split ticker for checking if same stock of different stock exchange is selected or not
            stock_name = ""
            stock_ex= "US"
            stock_name = ticker #ticker.split(".")
            if price >= PENNY_STOCK_THRESHOLD and stock_name not in stocks_temp:
                stocks_temp[stock_name] = stock_ex
                count += 1
    # get back ticker
    for stock in stocks_temp:
        stocks.append(f"{stock}")
        # stocks.append(f"{stock}.{stocks_temp[stock]}")
    
    # return deque of stocks to focus on
    return stocks

def get_sells(stocks_temp, prev_data, key):
    get_stocks(stocks_temp, prev_data, key)

def get_buys(stocks_temp, prev_data, key):
    get_stocks(stocks_temp, prev_data, key)

def get_stocks(stocks_temp, prev_data, key):
    if(not key in prev_data):
        raise Exception(f"Missing key '{key}' in prev_data")
    
    for ticker in prev_data[key]:
        
        stock_name, stock_ex = ticker.split(".")
        if stock_name in stocks_temp:
            Notify.fatal("Cannot buy and sell the same stock.")
            quit(0)

        stocks_temp[stock_name] = stock_ex

def main():
    """
        Main Function
    """
    # make sure that market is open
    if not DEV_MODE and CHECK_MARKET:
        if args.t:
            Notify.for_input("Check Market? (y/n) : ")
            confirm = input().strip().lower()
            print("")
        else:
            confirm = "y"
        if is_open() or confirm == "n":
            pass
        else:
            Notify.fatal("Market is closed at the moment, aborting.")
            print("")
            quit(0)
    # else:
    #     Notify.warn("You are in developer mode, if not intended, please quit.")
    #     Notify.info("Press ENTER to continue, Ctrl+C to quit")
    #     input()

    # allow market to settle to launch Ichimoku strategy
    if IDLE_DELAY == 0:
        Notify.info("Skipped Idle phase")
    else:
        Notify.info(f"Entered Idle phase at {datetime.datetime.now(TZ).strftime('%H:%M:%S')}")
        master_logger.info(f"Entered Idle phase")
        Notify.info(f"\tExpected release : after {IDLE_DELAY // 60} minutes")
        print("")
        sleep(IDLE_DELAY)

    master_logger.info("Idle phase complete")
    # find relevant stocks to focus on
    Notify.info("Finding stocks to focus on .....")
    try:
        stocks_to_focus = fetch_stocks()
    except Exception as ex:
        print(f'Exception was {ex}')
        stocks_to_focus = []
        Notify.fatal("Could not fetch relevant stocks. Verify Network connection and check logs for details.")
        master_logger.critical("Could not fetch relevant stocks, Most possibly due to network error")
        quit(0)
    Notify.info("\tStatus : Complete")
    master_logger.info("Successfully found relevant stocks")
    print("")

    # setup traders and begin trade
    master = Master(PERIOD_INTERVAL, master_logger, FEASIBLE_PERCENT, ACCOUNT, PACK_UP, DEV_MODE)
    master.validate_repo()
    master.lineup_traders(stocks_to_focus)
    master.init_traders(args.t)
    master.start_trading(args.t)

    # trading in over by this point
    Notify.info("Trading complete")
    master_logger.info("Trading complete")

    # initiate packup
    del master
    quit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        Notify.fatal("Operation cancelled by user.")
        master_logger.critical("Operation cancelled by user")
        quit(0)
    except Exception as err:
        Notify.fatal("Encountered fatal error. Check log for details. Aborting")

        master_logger.critical("Trade abort due to unexpected error : ", err)
