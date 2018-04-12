# -*- encoding: utf8 -*-
'''
Created on 4 Dec 2017

@author: MetalInvest
'''
try:
    from kuanke.user_space_api import *
except:
    pass
from jqdata import *
from common_include import *
from ta_analysis import *
from oop_strategy_frame import *
from position_control_analysis import *
from rsrs_timing import *

'''==================================调仓条件相关规则========================================='''


# '''===========带权重的退出判断基类==========='''
class Weight_Base(Rule):
    @property
    def weight(self):
        return self._params.get('weight', 1)


# '''-------------------------调仓时间控制器-----------------------'''
class Time_condition(Weight_Base):
    def __init__(self, params):
        Weight_Base.__init__(self, params)
        # 配置调仓时间 times为二维数组，示例[[10,30],[14,30]] 表示 10:30和14：30分调仓
        self.times = params.get('times', [])

    def update_params(self, context, params):
        Weight_Base.update_params(self, context, params)
        self.times = params.get('times', self.times)
        pass

    def handle_data(self, context, data):
        hour = context.current_dt.hour
        minute = context.current_dt.minute
        self.is_to_return = not [hour, minute] in self.times
        pass

    def __str__(self):
        return '调仓时间控制器: [调仓时间: %s ]' % (
            str(['%d:%d' % (x[0], x[1]) for x in self.times]))


# '''-------------------------调仓日计数器-----------------------'''
class Period_condition(Weight_Base):
    def __init__(self, params):
        Weight_Base.__init__(self, params)
        # 调仓日计数器，单位：日
        self.period = params.get('period', 3)
        self.day_count = 0
        self.mark_today = {}

    def update_params(self, context, params):
        Weight_Base.update_params(self, context, params)
        self.period = params.get('period', self.period)
        self.mark_today = {}

    def handle_data(self, context, data):
        self.is_to_return = self.day_count % self.period != 0 or (self.mark_today[context.current_dt.date()] if context.current_dt.date() in self.mark_today else False)
        
        if context.current_dt.date() not in self.mark_today: # only increment once per day
            self.log.info("调仓日计数 [%d]" % (self.day_count))
            self.mark_today[context.current_dt.date()]=self.is_to_return
            self.day_count += 1
        pass

    def on_sell_stock(self, position, order, is_normal, pindex=0,context=None):
        if not is_normal:
            # 个股止损止盈时，即非正常卖股时，重置计数，原策略是这么写的
            self.day_count = 0
            self.mark_today = {}
        pass

    # 清仓时调用的函数
    def on_clear_position(self, context, new_pindexs=[0]):
        self.day_count = 0
        self.mark_today = {}
        # if self.g.curve_protect:
        #     self.day_count = self.period-2
        #     self.g.curve_protect = False
        pass

    def __str__(self):
        return '调仓日计数器:[调仓频率: %d日] [调仓日计数 %d]' % (
            self.period, self.day_count)


'''===================================调仓相关============================'''


# '''---------------卖出股票规则--------------'''
class Sell_stocks(Rule):
    def __init__(self, params):
        Rule.__init__(self, params)
        self.use_short_filter = params.get('use_short_filter', False)
        self.money_fund = params.get('money_fund', ['511880.XSHG'])
        
    def handle_data(self, context, data):
        to_sell = context.portfolio.positions.keys()
        if self.use_short_filter:
            cta = checkTAIndicator_OR({
                'TA_Indicators':[
                                (TaType.MACD,'240m',233),
                                (TaType.MACD,'120m',233),
                                (TaType.MACD,'60m',233),
                                (TaType.BOLL, '240m',100),
                                (TaType.BOLL_UPPER, '1d',100),
                                ],
                'isLong':False})
            to_sell = cta.filter(context, data,to_sell)
        self.g.monitor_buy_list = [stock for stock in self.g.monitor_buy_list if stock not in to_sell]
        self.adjust(context, data, self.g.monitor_buy_list)

    def adjust(self, context, data, buy_stocks):
        # 卖出不在待买股票列表中的股票
        # 对于因停牌等原因没有卖出的股票则继续持有
        for pindex in self.g.op_pindexs:
            for stock in context.subportfolios[pindex].long_positions.keys():
                if stock not in buy_stocks and stock not in self.money_fund:
                    position = context.subportfolios[pindex].long_positions[stock]
                    self.g.close_position(self, position, True, pindex)
                    
    def recordTrade(self, stock_list):
        for stock in stock_list:
            biaoLiStatus = self.g.monitor_short_cm.getGaugeStockList(stock).values
            _, ta_type, period = self.g.short_record[stock] if stock in self.g.short_record else ([(nan, nan), (nan, nan), (nan, nan)], None, None)
            self.g.short_record[stock] = (biaoLiStatus, ta_type, period)

    def __str__(self):
        return '股票调仓卖出规则：卖出不在buy_stocks的股票'


# '''---------------买入股票规则--------------'''
class Buy_stocks(Rule):
    def __init__(self, params):
        Rule.__init__(self, params)
        self.buy_count = params.get('buy_count', 3)
        self.use_long_filter = params.get('use_long_filter', False)
        self.use_short_filter = params.get('use_short_filter', False)
        self.to_buy = []

    def update_params(self, context, params):
        Rule.update_params(self, context, params)
        self.buy_count = params.get('buy_count', self.buy_count)

    def handle_data(self, context, data):
        self.to_buy = self.g.monitor_buy_list
        self.log.info("待选股票: "+join_list([show_stock(stock) for stock in self.to_buy], ' ', 10))
        if self.use_short_filter:
            self.to_buy = self.ta_short_filter(context, data, self.to_buy)
        if context.current_dt.hour >= 14:
            if self.use_long_filter:
                self.to_buy = self.ta_long_filter(context, data, self.to_buy) 
            self.adjust(context, data, self.to_buy)

    def ta_long_filter(self, context, data, to_buy):
        cta = checkTAIndicator_OR({
            'TA_Indicators':[
                            # (TaType.MACD_ZERO,'60m',233),
                            (TaType.TRIX_STATUS, '240m', 100),
                            # (TaType.MACD_STATUS, '240m', 100),
                            (TaType.RSI, '240m', 100)
                            ],
            'isLong':True,
            'use_latest_data':True})
        to_buy = cta.filter(context, data,to_buy)
        return to_buy

    def ta_short_filter(self, context, data, to_buy):
        cti = checkTAIndicator_OR({
            'TA_Indicators':[
                            (TaType.MACD,'1d',233),
                            (TaType.BOLL, '1d',100),
                            (TaType.TRIX_STATUS, '1d', 100),
                            (TaType.BOLL_MACD,'1d',233),
                            (TaType.KDJ_CROSS, '1d', 100)
                            ],
            'isLong':False, 
            'use_latest_data':True})
        not_to_buy = cti.filter(context, data, to_buy)
        to_buy = [stock for stock in to_buy if stock not in not_to_buy]
        return to_buy
        
    def adjust(self, context, data, buy_stocks):
        # 买入股票
        # 始终保持持仓数目为g.buy_stock_count
        # 根据股票数量分仓
        # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
        for pindex in self.g.op_pindexs:
            position_count = len(context.subportfolios[pindex].long_positions)
            if self.buy_count > position_count:
                value = context.subportfolios[pindex].available_cash / (self.buy_count - position_count)
                for stock in buy_stocks:
                    if stock in self.g.sell_stocks:
                        continue
                    if stock not in context.subportfolios[pindex].long_positions.keys():
                        if self.g.open_position(self, stock, value, pindex):
                            if len(context.subportfolios[pindex].long_positions) == self.buy_count:
                                break
        pass

    def after_trading_end(self, context):
        self.g.sell_stocks = []
        self.to_buy = []

    def send_port_info(self, context):
        port_msg = [(context.portfolio.positions[stock].security, context.portfolio.positions[stock].total_amount * context.portfolio.positions[stock].price / context.portfolio.total_value) for stock in context.portfolio.positions]
        self.log.info(str(port_msg))
        if context.run_params.type == 'sim_trade':
            send_message(port_msg, channel='weixin')
        
    def recordTrade(self, stock_list):
        for stock in stock_list:
            biaoLiStatus = self.g.monitor_long_cm.getGaugeStockList(stock).values
            _, ta_type, period = self.g.long_record[stock] if stock in self.g.long_record else ([(nan, nan), (nan, nan), (nan, nan)], None, None)
            self.g.long_record[stock] = (biaoLiStatus, ta_type, period)

    def __str__(self):
        return '股票调仓买入规则：现金平分式买入股票达目标股票数'

class Buy_stocks_portion(Buy_stocks):
    def __init__(self,params):
        Rule.__init__(self, params)
        self.buy_count = params.get('buy_count',3)
    def update_params(self,context,params):
        self.buy_count = params.get('buy_count',self.buy_count)
    def handle_data(self, context, data):
        self.adjust(context, data, self.g.monitor_buy_list)
    def adjust(self,context,data,buy_stocks):
        if self.is_to_return:
            self.log_warn('无法执行买入!! self.is_to_return 未开启')
            return
        for pindex in self.g.op_pindexs:
            position_count = len(context.subportfolios[pindex].positions)
            if self.buy_count > position_count:
                buy_num = self.buy_count - position_count
                portion_gen = generate_portion(buy_num)
                available_cash = context.subportfolios[pindex].available_cash
                for stock in buy_stocks:
                    if stock in self.g.sell_stocks:
                        continue
                    if context.subportfolios[pindex].long_positions[stock].total_amount == 0:
                        buy_portion = portion_gen.next()
                        value = available_cash * buy_portion
                        if self.g.open_position(self, stock, value, pindex):
                            if len(context.subportfolios[pindex].long_positions) == self.buy_count:
                                break
        pass
    def after_trading_end(self, context):
        self.g.sell_stocks = []
    def __str__(self):
        return '股票调仓买入规则：现金比重式买入股票达目标股票数'  

class Buy_stocks_var(Buy_stocks):
    """使用 VaR 方法做调仓控制"""
    def __init__(self, params):
        Buy_stocks.__init__(self, params)
        self.money_fund = params.get('money_fund', ['511880.XSHG'])
        self.adjust_pos = params.get('adjust_pos', True)
        self.equal_pos = params.get('equal_pos', False)
        self.p_value = params.get('p_val', 2.58)
        self.risk_var = params.get('risk_var', 0.13)
        self.pc_var = None

    def adjust(self, context, data, buy_stocks):
        if not self.pc_var:
            # 设置 VaR 仓位控制参数。风险敞口: 0.05,
            # 正态分布概率表，标准差倍数以及置信率: 0.96, 95%; 2.06, 96%; 2.18, 97%; 2.34, 98%; 2.58, 99%; 5, 99.9999%
            # 赋闲资金可以买卖银华日利做现金管理: ['511880.XSHG']
            self.pc_var = PositionControlVar(context, self.risk_var, self.p_value, self.money_fund, self.equal_pos)
        if self.is_to_return:
            self.log_warn('无法执行买入!! self.is_to_return 未开启')
            return
        
        if self.adjust_pos:
            self.adjust_all_pos(context, data, buy_stocks)
        else:
            self.adjust_new_pos(context, data, buy_stocks)
    
    def adjust_new_pos(self, context, data, buy_stocks):
        for pindex in self.g.op_pindexs:
            position_count = len([stock for stock in context.subportfolios[pindex].positions.keys() if stock not in self.money_fund and stock not in buy_stocks])
            trade_ratio = {}
            if self.buy_count > position_count:
                buy_num = self.buy_count - position_count
                trade_ratio = self.pc_var.buy_the_stocks(context, buy_stocks[:buy_num])
            else:
                trade_ratio = self.pc_var.func_rebalance(context)

            # sell money_fund if not in list
            for stock in context.subportfolios[pindex].long_positions.keys():
                position = context.subportfolios[pindex].long_positions[stock]
                if stock in self.money_fund: 
                    if (stock not in trade_ratio or trade_ratio[stock] == 0.0):
                        self.g.close_position(self, position, True, pindex)
                    else:
                        self.g.open_position(self, stock, context.subportfolios[pindex].total_value*trade_ratio[stock],pindex)
                        
            for stock in trade_ratio:
                if stock in self.g.sell_stocks and stock not in self.money_fund:
                    continue
                if context.subportfolios[pindex].long_positions[stock].total_amount == 0:
                    if self.g.open_position(self, stock, context.subportfolios[pindex].total_value*trade_ratio[stock],pindex):
                        if len(context.subportfolios[pindex].long_positions) == self.buy_count+1:
                            break        
        
    def adjust_all_pos(self, context, data, buy_stocks):
        # 买入股票或者进行调仓
        # 始终保持持仓数目为g.buy_count
        for pindex in self.g.op_pindexs:
            to_buy_num = len(buy_stocks)
            # exclude money_fund
            holding_positon_exclude_money_fund = [stock for stock in context.subportfolios[pindex].positions.keys() if stock not in self.money_fund]
            position_count = len(holding_positon_exclude_money_fund)
            trade_ratio = {}
            if self.buy_count <= position_count+to_buy_num: # 满仓数
                buy_num = self.buy_count - position_count
                trade_ratio = self.pc_var.buy_the_stocks(context, holding_positon_exclude_money_fund+buy_stocks[:buy_num])
            else: # 分仓数
                trade_ratio = self.pc_var.buy_the_stocks(context, holding_positon_exclude_money_fund+buy_stocks)

            current_ratio = self.g.getCurrentPosRatio(context)
            order_stocks = self.getOrderByRatio(current_ratio, trade_ratio)
            for stock in order_stocks:
                if stock in self.g.sell_stocks:
                    continue
                if self.g.open_position(self, stock, context.subportfolios[pindex].total_value*trade_ratio[stock],pindex):
                    pass
    
    def getOrderByRatio(self, current_ratio, target_ratio):
        diff_ratio = [(stock, target_ratio[stock]-current_ratio[stock]) for stock in target_ratio if stock in current_ratio] \
                    + [(stock, target_ratio[stock]) for stock in target_ratio if stock not in current_ratio] \
                    + [(stock, 0.0) for stock in current_ratio if stock not in target_ratio]
        diff_ratio.sort(key=lambda x: x[1]) # asc
        return [stock for stock,_ in diff_ratio]
    
    def __str__(self):
        return '股票调仓买入规则：使用 VaR 方式买入或者调整股票达目标股票数'
    
class Sell_stocks_pair(Sell_stocks):
    def __init__(self,params):
        Sell_stocks.__init__(self, params)
        self.buy_count = params.get('buy_count', 2)
        
    def handle_data(self, context, data):
        if self.g.pair_zscore and len(self.g.monitor_buy_list)>1:
            final_buy_list = []
            i = 0
            while i < len(self.g.monitor_buy_list) and i < self.buy_count:
                if self.g.pair_zscore[int(i/2)] > 1:
                    final_buy_list.append(self.g.monitor_buy_list[i])  
                elif self.g.pair_zscore[int(i/2)] < -1:
                    final_buy_list.append(self.g.monitor_buy_list[i+1])
                else:
                    if self.g.pair_zscore[int(i/2)] >= 0:
                        final_buy_list = final_buy_list + self.g.monitor_buy_list
                    else:
                        final_buy_list = final_buy_list + self.g.monitor_buy_list
                i += 2
            self.adjust(context, data, final_buy_list)
        else:
            self.adjust(context, data, [])

    def __str__(self):
        return '股票调仓买入规则：配对交易卖出'

class Buy_stocks_pair(Buy_stocks_var):
    def __init__(self,params):
        Buy_stocks_var.__init__(self, params)
        self.buy_count = params.get('buy_count', 2)
        
    def handle_data(self, context, data):
        if self.g.pair_zscore and len(self.g.monitor_buy_list) > 1:
            final_buy_list = []
            i = 0
            while i < len(self.g.monitor_buy_list) and i < self.buy_count:            
                if self.g.pair_zscore[int(i/2)] > 1:
                    final_buy_list.append(self.g.monitor_buy_list[i])  
                elif self.g.pair_zscore[int(i/2)] < -1:
                    final_buy_list.append(self.g.monitor_buy_list[i+1])
                else:
                    if self.g.pair_zscore[int(i/2)] >= 0:
                        final_buy_list = final_buy_list + self.g.monitor_buy_list
                    else:
                        final_buy_list = final_buy_list + self.g.monitor_buy_list
                i += 2
            self.adjust(context, data, final_buy_list)
        else:
            self.adjust(context, data, [])
            
        self.send_port_info(context)
        

    def __str__(self):
        return '股票调仓买入规则：配对交易买入'
    

class Relative_Index_Timing(Rule):
    def __init__(self, params):
        self.market_list = params.get('market_list', ['000300.XSHG', '000016.XSHG', '399333.XSHE', '000905.XSHG', '399673.XSHE'])
        self.M = params.get('M', 600)
        self.N = params.get('N', 18)
        self.buy = params.get('buy', 0.7)
        self.sell = params.get('sell', -0.7)
        self.default_index = self.market_list[0]
        self.rsrs_check = RSRS_Market_Timing({'market_list': self.market_list,
                                              'M':self.M,
                                              'N':self.N,
                                              'buy':self.buy,
                                              'sell':self.sell})
        self.isInitialized = False
        
    def before_trading_start(self, context):
        Rule.before_trading_start(self, context)
        if not self.isInitialized:
            self.rsrs_check.calculate_RSRS()
            self.isInitialized = True
        else:
            self.rsrs_check.add_new_RSRS()
            
        for market in self.market_list:
            self.g.market_timing_check[market]=self.rsrs_check.check_timing(market)
        self.log.info("Index timing check: {0}".format(self.g.market_timing_check))
        
    def after_trading_end(self, context):
        Rule.after_trading_end(self, context)
        self.g.stock_index_dict = {}
        self.g.market_timing_check = {}
        
    def build_stock_index_dict(self, context):
        # find the index for candidate stock by largest correlation
        period = 250
        stock_symbol_list = [stock for stock in list(set(context.portfolio.positions.keys() + self.g.monitor_buy_list)) if stock not in g.money_fund]
        for stock in stock_symbol_list:
            current_max_corr = 0
            stock_df = attribute_history(stock, period, '1d', 'close', df=False)
            for idx in self.market_list:
                index_df = attribute_history(idx, period, '1d', 'close', df=False)
                corr = np.corrcoef(stock_df['close'],index_df['close'])[0,1]
                if corr >= current_max_corr:
                    self.g.stock_index_dict[stock] = idx
                    current_max_corr = corr
            if stock not in self.g.stock_index_dict:
                self.g.stock_index_dict[stock] = self.default_index
                self.log.info("{0} set to default index {1}".format(stock, self.default_index))
        self.log.info("stock index correlation matrix: {0}".format(self.g.stock_index_dict))
        
    def handle_data(self, context, data):
        self.build_stock_index_dict(context)
        stocks_to_check = [stock for stock in list(set(context.portfolio.positions.keys() + self.g.monitor_buy_list)) if stock not in g.money_fund]
        for stock in stocks_to_check:
            market = self.g.stock_index_dict[stock]
            if self.g.market_timing_check[market] == -1:
                self.g.sell_stocks.append(stock)
                if stock in context.portfolio.positions.keys():
                    self.g.close_position(self, context.portfolio.positions[stock], True, 0)
                if stock in self.g.monitor_buy_list:
                    self.g.monitor_buy_list.remove(stock)
#             if self.g.market_timing_check[market] != 1:
#                 if stock in self.g.monitor_buy_list:
#                     self.g.monitor_buy_list.remove(stock)
        self.log.info("candidate stocks: {0} closed position: {1}".format(self.g.monitor_buy_list, self.g.sell_stocks))
    def __str__(self):
        return '股票精确择时'