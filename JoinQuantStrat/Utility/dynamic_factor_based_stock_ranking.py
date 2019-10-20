# -*- encoding: utf8 -*-
'''
Created on 2 Aug 2017

@author: MetalInvest
'''
try:
    from kuanke.user_space_api import *         
except ImportError as ie:
    print(str(ie))
from jqdata import *
import numpy as np
import pandas as pd
import math
from jqfactor import *
from jqdata import *
from jqlib.technical_analysis import *


class Dynamic_factor_based_stock_ranking(object):
    '''
    This class use JQ interface to periodically rank existing factors based on IC and IR,
    and select stocks out of the ranking results
    '''
    def __init__(self, params):
        self.stock_num = params.get('stock_num', 5)
        self.index_scope = params.get('index_scope', 'hs300')
        self.period = params.get('period', 'month_3')
        self.model = params.get('model', 'long_only')
        self.category = params.get('category', ['quality', 'basics', 'emotion', 'growth', 'risk', 'pershare', 'barra', 'technical', 'momentum'])
        self.factor_gauge = params.get('factor_gauge', 'ir')
        self.factor_num = params.get('factor_num', 10)
        self.factor_date_count = params.get('factor_date_count', 1)
        self.factor_method = params.get('factor_method', 'factor_intersection') # ranking_score
        self.ic_mean_threthold = params.get('ic_mean_threthold', 0.02)
        
    def get_idx_code(self, scope):
        if scope == 'hs300':
            return '000300.XSHG'
        elif scope == 'zz500':
            return '000905.XSHG'
        elif scope == 'zz800':
            return '000906.XSHG'
        else:
            return '000300.XSHG'
    
    def gaugeStocks(self, context):
        factor_rank = get_factor_kanban_values(universe=self.index_scope, bt_cycle=self.period, model = self.model, category=self.category)  
        
        factor_rank = factor_rank[factor_rank['ic_mean'] >= self.ic_mean_threthold]
        
        factor_rank.sort_values(by=self.factor_gauge, inplace=True, ascending=False)
        
        factor_code_list = factor_rank['code'].head(self.factor_num).tolist()
        
        print(factor_code_list)
        
        index_code = self.get_idx_code(self.index_scope)
        
        stock_list = get_index_stocks(index_code)
        
        stock_factor_data = get_factor_values(securities=stock_list, factors=factor_code_list, count=self.factor_date_count, end_date=context.previous_date)
        
        if self.factor_method == 'factor_intersection':
            ranked_stock_list = {}
            for code in factor_code_list:
                factor_stock_ranking = stock_factor_data[code].T
                factor_stock_ranking.sort_values(by=factor_stock_ranking.columns[0], inplace=True, ascending=False)
                ranked_stock_list[code] = factor_stock_ranking.index[:self.stock_num].tolist()
            
            selected_stocks = []
            for code in ranked_stock_list:
                selected_stocks = [stock for stock in ranked_stock_list[code] if stock in selected_stocks] if selected_stocks else ranked_stock_list[code]
            
            return selected_stocks[:self.stock_num] if len(selected_stocks) > self.stock_num else selected_stocks
            
        elif self.factor_method == 'ranking_score':
            ranked_stock_score = None
            for code in factor_code_list:
                factor_stock_tmp = stock_factor_data[code].T
                factor_stock_tmp.rename({factor_stock_tmp.columns[0]:code},axis=1, inplace=True)
                ranked_stock_score = factor_stock_tmp if ranked_stock_score is None else ranked_stock_score.join(factor_stock_tmp)
            
            # sum all factors
            ranked_stock_score["sum_rank_score"] = ranked_stock_score.sum(axis=1)
            
            return ranked_stock_score.sort_values(by="sum_rank_score", inplace=False, ascending=False).index[:self.stock_num].tolist()
        else:
            print("We shouldn't be HERE")
        
            
            
        