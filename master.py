import datetime
import json
import os
from collections import deque
from time import sleep
from library import Notify, get_live_price
from trader import Trader, DATA_LIMIT
import pytz

TZ = pytz.timezone('Europe/London')

# Manages all the traders
class Master:
    def __init__(self, PERIOD_INTERVAL, master_logger, FEASIBLE_PERCENT, ACCOUNT, PACK_UP, DEV_MODE):
        self.traders = deque()
        self.period = PERIOD_INTERVAL
        self.logger = master_logger
        self.feasible_percent = FEASIBLE_PERCENT
        self.account = ACCOUNT
        self.pack_up = PACK_UP
        self.isDevMode = DEV_MODE
        
    # check if required directories exist, if not, make them
    @staticmethod
    def validate_repo():
        today = datetime.date.today().strftime("%d-%m-%Y")
        if not os.path.exists(".\\database"):
            os.mkdir("database")
        os.chdir("database")
        if not os.path.exists(today):
            os.mkdir(today)
        os.chdir(today)

    # allocate tickers to traders
    def lineup_traders(self, tickers):
        global ml
        count = 1
        for ticker in tickers:
            self.traders.append(Trader(count, ticker, self.account))
            Notify.info(f"Successfully connected Trader #{count} to {ticker}", delay=0.01)
            count += 1
        self.logger.info("Trader lineup complete")
        print("")

    # initialise traders
    def init_traders(self, Tmode=False):
        global ml

        Notify.info("Traders are in Observation phase")
        self.logger.info("Traders entered Observation Phase")
        if not Tmode:
            self.print_progress_bar(0, 80, prefix='Progress:', suffix='Complete', length=40)
            for i in range(DATA_LIMIT):
                for trader in self.traders:
                    trader.get_initial_data()
                self.print_progress_bar(i + 1, 80, prefix='\tProgress:', suffix='Complete', length=40)
                sleep(self.period)
        Notify.info("\tStatus : Complete")
        self.logger.info("Observation Phase complete")
        print("")

    def print_progress_bar(self, iteration, total, prefix='', suffix='', decimals=1, length=100, fill='█', print_end="\r"):
        """
            Call in a loop to create terminal progress bar
            @params:
                iteration   - Required  : current iteration (Int)
                total       - Required  : total iterations (Int)
                prefix      - Optional  : prefix string (Str)
                suffix      - Optional  : suffix string (Str)
                decimals    - Optional  : positive number of decimals in percent complete (Int)
                length      - Optional  : character length of bar (Int)
                fill        - Optional  : bar fill character (Str)
                printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
        """
        percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
        filled_length = int(length * iteration // total)
        bar = fill * filled_length + ' ' * (length - filled_length)
        print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end=print_end)
        # print new line on complete
        if iteration == total:
            print()
            
    # trading begins
    def start_trading(self, Tmode=False):
        global ml

        now = datetime.datetime.now(TZ)
        Notify.info("Trading has begun")
        self.logger.info("Trading has begun")
        count = 1
        if not Tmode:
            while now.time() < self.pack_up or self.is_dev_mode:
                try:
                    for trader in self.traders:
                        trader.run()
                    self.logger.info(f"Completed round {count}")
                    sleep(self.period)
                except Exception as e:
                    Notify.fatal("Trading has been aborted")
                    self.logger.critical("Trade abort due to unexpected error : ", e)
                    quit(0)
                finally:
                    now = datetime.datetime.now(TZ)
                    count += 1
        else:
            Notify.info("Confirming access to live stock price...")
            self.logger.info("Confirming access to live stock price...")
            for trader in self.traders:
                try:
                    get_live_price(trader.ticker)
                except Exception as e:
                    Notify.fatal("Error in fetching live stock price. Aborting")
                    self.logger.critical("Error in fetching live stock price : ", e)

    # save master data
    def __del__(self):
        # load previous day's data
        prev_data = json.loads(open("..\\user_info.json").read())
        username = prev_data['username']
        # debug
        account_balance_prev = prev_data["account_balance"]
        # get new data from trader's database
        account_balance_new = account_balance_prev * (1 - self.feasible_percent) + self.account
        profit = account_balance_new - account_balance_prev
        # set up new data
        new_data = dict()
        new_data['username'] = username
        new_data["account_balance"] = account_balance_new
        new_data["stocks_to_sell"] = dict()
        new_data["stocks_to_buy_back"] = dict()
        # grab data from trader database
        for trader in self.traders:
            # check owned stocks
            if trader.IN_LONG_TRADE:
                new_data["stocks_to_sell"][trader.ticker] = {"buffer_price": trader.price_for_buffer}
            # check owed stocks
            if trader.IN_SHORT_TRADE:
                new_data["stocks_to_buy_back"][trader.ticker] = {"buffer_price": trader.price_for_buffer}
            # save trader database in respective files
            del trader
        # save master database
        with open("..\\user_info.json", "w") as fp:
            fp.write(json.dumps(new_data, indent=4))
        # output profit
        Notify.info(f"\n\nNet Profit : $ {profit} \n")
        self.logger.info(f"\n\nNet Profit : $ {profit}  \n")
        Notify.info(f'Stocks owned : {len(new_data["stocks_to_sell"])}')
        self.logger.info(f'Stocks owned : {len(new_data["stocks_to_sell"])}')
        Notify.info(f'Stocks sold : {len(new_data["stocks_to_buy_back"])}')
        self.logger.info(f'Stocks sold : {len(new_data["stocks_to_buy_back"])}')