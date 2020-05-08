from keras.models import Model
from keras.layers import Dense, Dropout, LSTM, Input, Activation, concatenate, regularizers
from keras import optimizers
import numpy as np
np.random.seed(4)
from scipy.ndimage.interpolation import shift
import pandas as pd
from sklearn import preprocessing
import numpy as np
from pulp import *

from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt import risk_models
from pypfopt import expected_returns
from pypfopt.discrete_allocation import DiscreteAllocation, get_latest_prices






def fun_column(matrix, i):
    return [row[i] for row in matrix]

def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]




def transformDataset(input_path,input_sep, output_path, output_sep,metadata_input_path, metadata_sep, filter_sectors = None, n_tickers = 'empty', n_last_values = 250 ):
    # filter out tickers that have no values in the last n days
    df = pd.read_csv(input_path, sep=input_sep)
    df['RN'] = df.sort_values(['date'], ascending=[False]) \
                   .groupby(['ticker']) \
                   .cumcount() + 1
    df = df[df['RN'] <= n_last_values]

    # filter out tickers that have no values in the last n days from the metadata table
    df_metadata = pd.read_csv(metadata_input_path, sep=metadata_sep)
    metadata_filtered = df_metadata[df_metadata.sector.isin(filter_sectors)]
    metadata_filtered = metadata_filtered[metadata_filtered.ticker.isin(pd.unique(df['ticker']))]

    # get n_tickers within each sector group
    i = 0
    for sector in filter_sectors:
        if i == 0:
            tickers = metadata_filtered[metadata_filtered.sector == sector].head(n_tickers)

        else:
            tickers = pd.concat([tickers, metadata_filtered[metadata_filtered.sector == sector].head(n_tickers)])

        i = i + 1

    # filter out the n_tikcers within each sector group from main dataset
    df = df[df.ticker.isin(tickers['ticker'])]
    l_tickers = df.ticker.unique()

    # transform the dataset
    n = 1
    for i in l_tickers:

        print(i)
        if n == 1:

            df_stock = df[df.ticker == i]

            df_stock.date = pd.to_datetime(df_stock.date)
            df_stock = df_stock.set_index("date")

            df_stock = df_stock[['open', 'high', 'low', 'close', 'volume']]
            df_stock = df_stock.rename(
                columns={'open': i + '_Open', 'high': i + '_High', 'low': i + '_Low', 'close': i + '_Close',
                         'volume': i + '_Volume'})

        else:
            df_stock_new = df[df.ticker == i]

            df_stock_new.date = pd.to_datetime(df_stock_new.date)
            df_stock_new = df_stock_new.set_index("date")

            df_stock_new = df_stock_new[['open', 'high', 'low', 'close', 'volume']]
            df_stock_new = df_stock_new.rename(
                columns={'open': i + '_Open', 'high': i + '_High', 'low': i + '_Low', 'close': i + '_Close',
                         'volume': i + '_Volume'})

            df_stock = df_stock.merge(df_stock_new, how='outer', left_index=True, right_index=True)

        n = n + 1

    # get only last n_values and save it to disk
    df_n_last_vaues = df_stock.tail(n_last_values)
    df_n_last_vaues = df_n_last_vaues.dropna(axis='columns')

    df_n_last_vaues.to_csv(output_path, sep=output_sep)


def createDataset(df, history_points = 50):
    # dataset
    data = df.values
    data_normaliser = preprocessing.MinMaxScaler()
    data_normalised = data_normaliser.fit_transform(data)

    # using the last {history_points} open close high low volume data points, predict the next open value
    ohlcv_histories_normalised = np.array(
        [data_normalised[i:i + history_points].copy() for i in range(len(data_normalised) - history_points)])
    next_day_open_values_normalised = np.array(
        [data_normalised[:, 0][i + history_points].copy() for i in range(len(data_normalised) - history_points)])
    next_day_open_values_normalised = np.expand_dims(next_day_open_values_normalised, -1)

    next_day_open_values = np.array([data[:, 0][i + history_points].copy() for i in range(len(data) - history_points)])
    next_day_open_values = np.expand_dims(next_day_open_values, -1)

    y_normaliser = preprocessing.MinMaxScaler()
    y_normaliser.fit(next_day_open_values)

    def calc_ema(values, time_period):
        # https://www.investopedia.com/ask/answers/122314/what-exponential-moving-average-ema-formula-and-how-ema-calculated.asp
        sma = np.mean(values[:, 3])
        ema_values = [sma]
        k = 2 / (1 + time_period)
        for i in range(len(his) - time_period, len(his)):
            close = his[i][3]
            ema_values.append(close * k + ema_values[-1] * (1 - k))
        return ema_values[-1]

    technical_indicators = []
    for his in ohlcv_histories_normalised:
        # note since we are using his[3] we are taking the SMA of the closing price
        sma = np.mean(his[:, 3])
        macd = calc_ema(his, 12) - calc_ema(his, 26)
        returns = his[:, 3] / shift(his[:,3], 1, cval=np.NaN)
        returns = returns[-1]
        #technical_indicators.append(np.array([sma]))
        technical_indicators.append(np.array([sma,macd,returns]))

    technical_indicators = np.array(technical_indicators)

    tech_ind_scaler = preprocessing.MinMaxScaler()
    technical_indicators_normalised = tech_ind_scaler.fit_transform(technical_indicators)

    assert ohlcv_histories_normalised.shape[0] == next_day_open_values_normalised.shape[0] == \
           technical_indicators_normalised.shape[0]

    return next_day_open_values_normalised, next_day_open_values, ohlcv_histories_normalised, technical_indicators, data_normaliser, y_normaliser

def splitTrainTest(values, n, verbose = 0):
    train, test = values[:n], values[n:]
    if verbose != 0:
        print('Shape of training dataset: ' + str(train.shape))
        print('Shape of testing dataset: ' + str(test.shape))

    return train, test

def defineModel(ohlcv_histories_normalised,technical_indicators, verbose= 0 ):
    # define two sets of inputs
    lstm_input = Input(shape=(ohlcv_histories_normalised.shape[1], ohlcv_histories_normalised.shape[2]), name='lstm_input')
    dense_input = Input(shape=(technical_indicators.shape[1],), name='tech_input')

    # the first branch operates on the first input
    x = LSTM(50, name='lstm_0')(lstm_input)
    x = Dropout(0.2, name='lstm_dropout_0')(x)
    lstm_branch = Model(inputs=lstm_input, outputs=x)

    # the second branch opreates on the second input
    y = Dense(20, name='tech_dense_0')(dense_input)
    y = Activation("relu", name='tech_relu_0')(y)
    y = Dropout(0.2, name='tech_dropout_0')(y)
    technical_indicators_branch = Model(inputs=dense_input, outputs=y)

    # combine the output of the two branches
    combined = concatenate([lstm_branch.output, technical_indicators_branch.output], name='concatenate')

    z = Dense(64, activation="sigmoid", name='dense_pooling')(combined)
    z = Dense(1, activation="linear", name='dense_out')(z)

    # our model will accept the inputs of the two branches and
    # then output a single value
    model = Model(inputs=[lstm_branch.input, technical_indicators_branch.input], outputs=z)
    adam = optimizers.Adam(lr=0.0005)
    model.compile(optimizer=adam, loss='mse')
    if verbose != 0:
        model.summary()
    return model

def defineAutoencoder(num_stock, encoding_dim = 5, verbose=0):

    # connect all layers
    input = Input(shape=(num_stock,))

    encoded = Dense(encoding_dim, kernel_regularizer=regularizers.l2(0.00001),name ='Encoder_Input')(input)
    encoded = Activation("relu", name='Encoder_Activation_function')(encoded)
    encoded = Dropout(0.2, name='Encoder_Dropout')(encoded)

    decoded = Dense(num_stock, kernel_regularizer=regularizers.l2(0.00001), name ='Decoder_Input')(encoded)  # see 'Stacked Auto-Encoders' in paper
    decoded = Activation("linear", name='Decoder_Activation_function')(decoded)

    # construct and compile AE model
    autoencoder = Model(inputs=input, outputs=decoded)
    adam = optimizers.Adam(lr=0.0005)
    autoencoder.compile(optimizer=adam, loss='mean_squared_error')
    if verbose!= 0:
        autoencoder.summary()

    return autoencoder

def predictAutoencoder(autoencoder, data):
    # train autoencoder
    autoencoder.fit(data, data, shuffle=True, epochs=500, batch_size=50)
    # test/reconstruct market information matrix
    reconstruct = autoencoder.predict(data)

    return reconstruct


def getAverageReturns(df, index, days=None):
    '''

    :param df:
    :param index:
    :param days:
    :return:
    '''

    if days == None:
        average = np.average(df.iloc[:, index])*100
    else:
        average =  np.average(df.iloc[-days:, index])*100

    return average


def getAverageReturnsDF(stock_names , df_pct_change, df_result_close,df_original, forecasting_days, backtest_iteration):

    stocks_ranked = []

    stock_index = 0
    for stock_name in stock_names:
        stocks_ranked.append([   backtest_iteration
                                 , df_pct_change.iloc[:, stock_index].name
                                 , getAverageReturns(df=df_pct_change, index=stock_index)
                                 , getAverageReturns(df=df_pct_change, index=stock_index, days=10)
                                 , getAverageReturns(df=df_pct_change, index=stock_index, days=50)
                                 , getAverageReturns(df=df_pct_change, index=stock_index, days=100)
                                 , df_result_close.iloc[-forecasting_days - 1:, stock_index].head(1).iloc[0]
                                 ,df_original[df_pct_change.iloc[:, stock_index].name + '_Close'].tail(forecasting_days * backtest_iteration - forecasting_days + 1).iloc[0]])
        stock_index = stock_index + 1


    columns = ['backtest_iteration','stock_name', 'avg_returns', 'avg_returns_last10_days',
               'avg_returns_last50_days', 'avg_returns_last100_days', 'current_price','value_after_x_days']

    df = pd.DataFrame(stocks_ranked, columns=columns)
    df['delta'] = df['value_after_x_days'] - df['current_price']

    df = df.set_index('stock_name')
    return df


def getReconstructionErrorsDF(df_pct_change, reconstructed_data):

    array = []
    stocks_ranked = []
    num_columns = reconstructed_data.shape[1]
    for i in range(0, num_columns-1):
        diff = np.linalg.norm((df_pct_change.iloc[:, i] - reconstructed_data[:, i]))  # 2 norm difference
        array.append(float(diff))

    ranking = np.array(array).argsort()
    r = 1
    for stock_index in ranking:
        stocks_ranked.append([ r
                              ,stock_index
                              ,df_pct_change.iloc[:, stock_index].name
                              ,array[stock_index]
                              ])
        r = r + 1

    columns = ['ranking','stock_index', 'stock_name' ,'recreation_error']
    df = pd.DataFrame(stocks_ranked, columns=columns)
    df = df.set_index('stock_name')
    return df

def getLatentFeaturesSimilariryDF(df_pct_change, latent_features):
    stocks_latent_feature = []
    array = []
    num_columns = latent_features.shape[0]
    #for i in range(0, num_columns - 1):
    for i in range(0, num_columns ):
        l2norm = np.linalg.norm(latent_features[i, :])  # 2 norm difference
        array.append(float(l2norm))



    stock_index = 0
    for similarity_score in array:
        stocks_latent_feature.append([stock_index
                                 ,similarity_score
                                 , df_pct_change.iloc[:, stock_index].name
                                 , ])
        stock_index = stock_index + 1

    columns = ['stock_index',
               'similarity_score'
               ,'stock_name']
    df = pd.DataFrame(stocks_latent_feature, columns=columns)
    df = df.set_index('stock_name')
    return df.sort_values(by=['similarity_score'], ascending=True)




def portfolio_selection(d,df_portfolio , ranking_colum ,  n_stocks_per_bin, budget ,n_bins,group_by = True):
    n_stocks_total = n_stocks_per_bin * n_bins
    if group_by == True:
        df_portfolio['rn'] = df_portfolio.sort_values([ranking_colum], ascending=[False]) \
                                         .groupby(['similarity_score_quartile']) \
                                         .cumcount() + 1

        df_portfolio_selected_stocks = df_portfolio[df_portfolio['rn'] <= n_stocks_per_bin]
        print(df_portfolio_selected_stocks.__len__())
    else:
        df_portfolio['rn'] = df_portfolio[ranking_colum].rank(method='max', ascending=False)
        df_portfolio_selected_stocks = df_portfolio[df_portfolio['rn'] <= n_stocks_total]
        print(df_portfolio_selected_stocks.__len__())

    var_names = ['x' + str(i) for i in range(n_stocks_total)]
    x_int = [pulp.LpVariable(i, lowBound=0, cat='Integer') for i in var_names]

    my_lp_problem = pulp.LpProblem("Portfolio_Selection_LP_Problem", pulp.LpMaximize)
    # Objective function
    my_lp_problem += lpSum([x_int[i] * df_portfolio_selected_stocks['current_price'].iloc[i] for i in range(n_stocks_total)]) <= budget
    # Constraints
    my_lp_problem += lpSum(
        [x_int[i] * df_portfolio_selected_stocks['current_price'].iloc[i] for i in range(n_stocks_total)])

    for i in range(n_stocks_total):
        my_lp_problem += x_int[i] * df_portfolio_selected_stocks['current_price'].iloc[
            i] <= (budget / n_stocks_total) * 0.5

    my_lp_problem.solve()
    pulp.LpStatus[my_lp_problem.status]


    bought_volume_arr = []
    for variable in my_lp_problem.variables():
        print("{} = {}".format(variable.name, variable.varValue))
        bought_volume_arr.append(variable.varValue)

    df_portfolio_selected_stocks['bought_volume'] = bought_volume_arr


    df_portfolio_selected_stocks['pnl'] = df_portfolio_selected_stocks['delta'] * df_portfolio_selected_stocks['bought_volume']
    print('Profit for iteration ' + str(d) + ': '  + str(df_portfolio_selected_stocks['pnl'].sum()))

    profits = [df_portfolio_selected_stocks['pnl'].sum()]

    return profits , df_portfolio_selected_stocks



def calcMarkowitzPortfolio(df, budget):

    # Calculate expected returns and sample covariance
    mu = expected_returns.mean_historical_return(df)
    S = risk_models.sample_cov(df)

    # Optimise for maximal Sharpe ratio
    ef = EfficientFrontier(mu, S)
    weights = ef.max_sharpe()
    cleaned_weights = ef.clean_weights()
    ef.portfolio_performance(verbose=False)

    latest_prices = get_latest_prices(df)
    da = DiscreteAllocation(weights, latest_prices, total_portfolio_value=budget, min_allocation=-1)
    discrete_allocation, discrete_leftover = da.lp_portfolio()

    return discrete_allocation, discrete_leftover, weights, cleaned_weights
