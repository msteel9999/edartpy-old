import datetime
import json
import pytz
from OpenSSL.SSL import SysCallError
from library import Notify, get_live_price, trader_logger

# number of observations of prices during initialisation phase, minimum value of 80
DATA_LIMIT = 80
TZ = pytz.timezone('Europe/London')
BUFFER_PERCENT = 0.06

class Trader:
    def __init__(self, number, ticker, account):
        self.account = account
        self.number = number
        self.ticker = ticker
        # store x values, equivalent to time
        self.time = [i for i in range(-25, DATA_LIMIT + 27)]
        # list for storing live price
        self.price = []
        # lists for storing Ichimoku params
        self.tenkan_data = []
        self.kijun_data = []
        self.chikou_data = []
        self.senkou_A_data = []
        self.senkou_B_data = []
        # x values for senkou A and senkou B
        self.x5 = []
        self.x6 = []
        # database to save activity of trader
        self.database = dict()
        self.database["Ticker"] = self.ticker
        self.database["Activity"] = dict()
        # other params used within trader class
        self.IN_SHORT_TRADE = False
        self.IN_LONG_TRADE = False
        self.STOCKS_TO_SELL = 0
        self.STOCKS_TO_BUY_BACK = 0
        self.price_for_buffer = 0
        self.sold_price = 0
        self.bought_price = 0
        # set params in accordance with previous day's data
        prev_data = json.loads(open("../user_info.json").read())
        # check if allotted stock has been bought the previous day or not, long trade
        if self.ticker in prev_data["stocks_to_sell"]:
            price = prev_data["stocks_to_sell"][self.ticker]["buffer_price"]
            self.IN_LONG_TRADE = True
            self.price_for_buffer = price
        # check if allotted stock has been sold the previous day or not, short trade
        if self.ticker in prev_data["stocks_to_buy_back"]:
            price = prev_data["stocks_to_buy_back"][self.ticker]["buffer_price"]
            self.IN_SHORT_TRADE = True
            self.price_for_buffer = price
        self.logger = trader_logger(self.ticker)
        self.logger.info("-" * 76)
        self.logger.info("-" * 27 + " NEW SESSION DETECTED " + "-" * 27)
        self.logger.info("-" * 76)

    def get_initial_data(self):
        try:
            self.price.append(get_live_price(self.ticker))
            self.logger.debug("Successfully fetched live price")
        except SysCallError:
            Notify.warn(
                f"[Trader #{self.number} {self.ticker}]: Encountered SysCallError while initialising parameters, trying recursion")
            self.logger.warning("Encountered SysCallError, trying recursion")
            self.get_initial_data()
        except Exception as e:
            Notify.warn(
                f"[Trader #{self.number} {self.ticker}]: Exception in getting initial data, trying recursion")
            self.logger.error(
                "Trying recursion due to uncommon Exception : ", e)
            self.get_initial_data()

    def buy(self, price, trade):
        # global ACCOUNT
        now = datetime.datetime.now(TZ).strftime('%H:%M:%S')
        self.bought_price = price
        self.logger.info("Bought stock, in ", trade, " trade, for $", price)

        #TODO - is account set property or just local to trader?
        self.account -= price
        self.database['Activity'][now] = {
            "trade": trade,
            "bought at": price
        }

    def sell(self, price, trade):
        # global ACCOUNT
        now = datetime.datetime.now(TZ).strftime('%H:%M:%S')
        self.sold_price = price
        self.logger.info("Sold stock, in ", trade, " trade, for $", price)
        self.account += price
        self.database['Activity'][now] = {
            "trade": trade,
            "sold at": price
        }

    def update_price(self):
        try:
            new_price = get_live_price(self.ticker)
            self.price.append(new_price)
            self.logger.info(
                "Successfully fetched price, local database updated")
        except SysCallError:
            Notify.warn(
                f"[Trader #{self.number} {self.ticker}] : Encountered SysCallError in updating price, trying recursion")
            self.logger.warning(
                "Encountered SysCallError while fetching live price, trying recursion")
            self.update_price()
        except Exception as e:
            Notify.warn(
                f"[Trader #{self.number} {self.ticker}] : Exception in updating price, trying recursion")
            self.logger.error(
                "Trying recursion, encountered uncommon exception : ", e)
            self.update_price()

    def update_data(self):
        self.update_price()
        self.time.append(self.time[-1] + 1)
        del self.time[0], self.price[0]

    # observe indicator and decide buy and sell
    def make_decision(self):
        # global ACCOUNT
        # update tenkan data
        self.tenkan_data = []
        for i in range(DATA_LIMIT - 9):
            tenkan_src = self.price[i:i + 9]
            self.tenkan_data.append((max(tenkan_src) + min(tenkan_src)) / 2)
        # update kijun data
        self.kijun_data = []
        for i in range(DATA_LIMIT - 26):
            kijun_src = self.price[i:i + 26]
            self.kijun_data.append((max(kijun_src) + min(kijun_src)) / 2)
        # update x values for senkou A and senkou B
        self.x5 = self.time[78:78 + DATA_LIMIT - 26]
        self.x6 = self.time[104:104 + DATA_LIMIT - 52]
        # update senkou A data
        self.senkou_A_data = [
            (self.tenkan_data[i + 17] + self.kijun_data[i]) / 2 for i in range(DATA_LIMIT - 26)]
        # update senkou B data
        self.senkou_B_data = []
        for i in range(DATA_LIMIT - 52):
            senkou_B_src = self.price[i:i + 52]
            self.senkou_B_data.append(
                (max(senkou_B_src) + min(senkou_B_src)) / 2)

        # get Ichimoku params for comparison
        x = self.time[26:26 + DATA_LIMIT][-1]
        curr_price = self.price[-1]
        tenkan = self.tenkan_data[-1]
        kijun = self.kijun_data[-1]
        sen_A = self.get_value(self.senkou_A_data, self.x5, x)
        sen_B = self.get_value(self.senkou_B_data, self.x6, x)
        self.logger.info(
            f"Current status - Price : {curr_price}, Tenkan : {tenkan}, Kijun : {kijun}, Senkou A : {sen_A}, Senkou B : {sen_B}")

        # conditions for long trade entry
        # If Kumo cloud is green and current price is above kumo, strong bullish signal
        cond1 = (sen_A > sen_B) and (curr_price >= sen_A)
        if cond1:
            self.logger.debug("Sensing strong bullish signal")
        # conditions for short trade entry
        # If Kumo cloud is red and current price is below kumo, strong bearish signal
        cond2 = (sen_A < sen_B) and (curr_price <= sen_A)
        if cond2:
            self.logger.debug("Sensing strong bearish signal")
        # check allocated money
        cond3 = curr_price < self.account

        # IF all conditions are right, long trade entry
        if cond1 and not self.IN_LONG_TRADE and cond3:
            self.buy(curr_price, "LONG")
            self.price_for_buffer = curr_price
            self.IN_LONG_TRADE = True
            self.STOCKS_TO_SELL += 1
        if not cond3:
            Notify.fatal(
                f"[Trader #{self.number} {self.ticker}] : Oops! Out of cash!")
            self.logger.critical("Trader out of cash to buy stocks!")
        # If all conditions are right, short trade entry
        if cond2 and not self.IN_SHORT_TRADE:
            self.sell(curr_price, "SHORT")
            self.price_for_buffer = curr_price
            self.IN_SHORT_TRADE = True
            self.STOCKS_TO_BUY_BACK += 1

        # setup buffer for stop loss and trade exit
        buffer = self.price_for_buffer * BUFFER_PERCENT
        cond4 = abs(curr_price - kijun) >= buffer

        # Get stopped out as the price moves through the buffer area beyond the Kijun
        if self.IN_LONG_TRADE:
            if cond4:
                self.sell(curr_price, "LONG")
                self.IN_LONG_TRADE = False
                self.STOCKS_TO_SELL -= 1
        if self.IN_SHORT_TRADE:
            if cond4 and cond3:
                self.buy(curr_price, "SHORT")
                self.IN_SHORT_TRADE = False
                self.STOCKS_TO_BUY_BACK -= 1
            if not cond3:
                Notify.fatal(
                    f"[Trader #{self.number} {self.ticker}] : Oops! Out of cash!")
                self.logger.critical("Trader out of cash to buy back stock !")

    # group update and decision call for convenience
    def run(self):
        self.update_data()
        self.make_decision()

    def __del__(self):
        with open(self.ticker + ".json", "w") as fp:
            fp.write(json.dumps(self.database, indent=4))
        self.logger.critical("Trader killed")

    def get_value(self, ref: list, x_src: list, x: float) -> float:
        """
            Helper function for traders, used to find Ichimoku components corresponding to entry from other components or price
        Args:
            ref: iterable from which corresponding entry should be found
            x_src: iterable containing param x
            x: an item, maybe a component value, maybe price

        Returns:

        """
        return ref[x_src.index(x)]
