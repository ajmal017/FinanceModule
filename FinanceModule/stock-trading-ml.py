
if __name__ == "__main__":  # confirms that the code is under main function
    import warnings
    import matplotlib.pyplot as plt
    from keras.models import Model
    import numpy as np
    import json
    from keras.callbacks import TensorBoard
    from FinanceModule.util import *
    import copy
    import pandas as pd
    from sklearn import preprocessing
    from datetime import datetime
    from multiprocessing import Pool
    import multiprocessing

    warnings.filterwarnings("error")
    os.environ["PATH"] += os.pathsep + 'lib/Graphviz2.38/bin/'
    print('-' * 50)
    print('PART I: Timeseries Cleaning')
    print('-' * 50)

    # general parameters
    fontsize = 12
    parallel_processes = multiprocessing.cpu_count() - 1

    # indicate folder to save, plus other options
    date = datetime.now().strftime('%Y-%m-%d_%H_%M')
    tensorboard = TensorBoard(log_dir='./logs/run_' + date)
    # save it in your callback list, where you can include other callbacks
    callbacks_list = [tensorboard]

    # script parameters
    test_setting = False
    plot_results = True
    stock_selection = False
    '''
     Note Multiprocessing cannot run when in the main session a keras backend was created before creating the worker pool. 
     E.g. Time Series Evaluation cannot run in the same script as time series forecasting. 
    '''
    timeseries_evaluation = False
    timeseries_forecasting =False
    portfolio_optimization = True


    verbose = 0

    # 0 Data Preparation
    history_points = 150
    test_split = 0.9
    n_forecast = 10
    n_tickers = 6000
    n_days = 250 * 4
    trading_days = 252
    sectors = ['FINANCE', 'CONSUMER SERVICES', 'TECHNOLOGY',
               'CAPITAL GOODS', 'BASIC INDUSTRIES', 'HEALTH CARE',
               'CONSUMER DURABLES', 'ENERGY', 'TRANSPORTATION', 'CONSUMER NON-DURABLES']


    # 1. Selection of least volatile stocks using autoencoders
    hidden_layers = 5
    batch_size = 500
    epochs = 500
    stock_selection_number = 500

    # 2. Forecasting using recurrent neural networks
    backtest_days = 200

    # 3. Portfolio Optimization parameters
    number_of_stocks = 1000


    """
    transformDataset( input_path='data/historical_stock_prices.csv', input_sep=','
                     , metadata_input_path = 'data/historical_stocks.csv', metadata_sep = ','
                     ,output_path='data/historical_stock_prices_original.csv', output_sep=';'
                     ,filter_sectors = sectors
                     ,n_tickers = n_tickers, n_last_values = n_days )
    
    """

    print('-' * 5 + 'Loading the dataset from disk')
    df_original = pd.read_csv('data/historical_stock_prices_original.csv', sep=';', index_col='date')
    df_original.index = pd.to_datetime(df_original.index)

    # 1. Selection of least volatile stocks using autoencoders
    if stock_selection:

        ## Deep Portfolio
        print('-' * 15 + 'PART IV: Autoencoder Deep Portfolio Optimization')
        print('-' * 20 + 'Create dataset')
        df_result_close = df_original.filter(like='Close', axis=1)

        new_columns = []
        [new_columns.append(c.split('_')[0]) for c in df_result_close.columns]
        df_result_close.columns = new_columns
        df_result_close = df_result_close.dropna(axis=1, how='any', thresh=0.90 * len(df_original))

        print('-' * 20 + 'Transform dataset')
        df = df_result_close

        df_pct_change = df_result_close.pct_change(1).astype(float)
        df_pct_change = df_pct_change.replace([np.inf, -np.inf], np.nan)
        df_pct_change = df_pct_change.fillna(method='ffill')
        # the percentage change function will make the first two rows equal to nan
        df_pct_change = df_pct_change.tail(len(df_pct_change) - 2)

        # remove columns where there is no change over a longer time period
        df_pct_change = df_pct_change[df_pct_change.columns[((df_pct_change == 0).mean() <= 0.05)]]

        # -------------------------------------------------------
        #           Step1: Recreation Error
        # -------------------------------------------------------
        print('-' * 20 + 'Step 1 : Returns vs. recreation error (recreation_error)')
        print('-' * 25 + 'Transform dataset with MinMax Scaler')
        df_scaler = preprocessing.MinMaxScaler()
        df_pct_change_normalised = df_scaler.fit_transform(df_pct_change)

        # define autoencoder
        print('-' * 25 + 'Define autoencoder model')
        num_stock = len(df_pct_change.columns)
        autoencoder = defineAutoencoder(num_stock=num_stock, encoding_dim=hidden_layers, verbose=verbose)
        #plot_model(autoencoder, to_file='img/model_autoencoder_1.png', show_shapes=True,
        #           show_layer_names=True)

        # train autoencoder
        print('-' * 25 + 'Train autoencoder model')
        autoencoder.fit(df_pct_change_normalised, df_pct_change_normalised, shuffle=False, epochs=epochs,
                        batch_size=batch_size,
                        verbose=verbose)

        # predict autoencoder
        print('-' * 25 + 'Predict autoencoder model')
        reconstruct = autoencoder.predict(df_pct_change_normalised)

        # Inverse transform dataset with MinMax Scaler
        print('-' * 25 + 'Inverse transform dataset with MinMax Scaler')
        reconstruct_real = df_scaler.inverse_transform(reconstruct)
        df_reconstruct_real = pd.DataFrame(data=reconstruct_real, columns=df_pct_change.columns)

        print('-' * 25 + 'Calculate L2 norm as reconstruction loss metric')
        df_recreation_error = getReconstructionErrorsDF(df_pct_change=df_pct_change
                                                        , reconstructed_data=reconstruct_real)

        filtered_stocks = df_recreation_error.head(stock_selection_number).index
        df_result_close_filtered = df_result_close[filtered_stocks]
        df_result_close_filtered.to_csv('data/df_result_close_filtered.csv', sep=';')

    df_result_close_filtered = pd.read_csv('data/df_result_close_filtered.csv', sep=';', index_col ='date')


    # Get tickers as a list
    print('-' * 5 + 'Getting list of unique tickers')
    l_tickers_new = df_result_close_filtered.columns.str.split('_')
    l_tickers_unique = np.unique(fun_column(l_tickers_new, 0))
    l_tickers_unique_chunks = list(chunks(l_tickers_unique, parallel_processes))


    # 2. Forecasting using recurrent neural networks
    if timeseries_forecasting:
        #for d in range(5, 8)[::-1]:
        for d in range(int(backtest_days/n_forecast)+1)[::-1]:

            if d != 0 and d > 10 and d < 16:
                print('-' * 5 + 'Backtest Iteration ' + str(d))
                df = df_original.head(len(df_original) - n_forecast * d)
                print('-' * 5 + 'Starting for loop over all tickers')
                j = 0
                for j_val in l_tickers_unique_chunks:
                    print('opening new pool: ' + str(j) + '/' + str(len(l_tickers_unique_chunks)))
                    pool = Pool(processes=parallel_processes)  # start 12 worker processes
                    i = 0
                    for val in j_val:
                        column = val
                        #print(column)
                        df_filtered = df.filter(regex='^' + column + '', axis=1)
                        #stock_forceasting(i, column, df_filtered, timeseries_evaluation, timeseries_forecasting)
                        if not os.path.isfile('data/intermediary/df_result_' + str(d) + '_' + column + '.csv'):
                            pool.apply_async(stock_forceasting,
                                             args=(i, column, df_filtered, timeseries_evaluation, timeseries_forecasting, l_tickers_unique, n_days, n_forecast, test_split, verbose, d, plot_results,fontsize))
                        i = i + 1
                    print('closing new pool')
                    pool.close()
                    pool.join()
                    j = j + 1

                for i in range(0, len(l_tickers_unique)):
                    column = l_tickers_unique[i]
                    try:
                        if timeseries_forecasting:
                            df_result_ticker = pd.read_csv('data/intermediary/df_result_' + str(d) + '_' + column + '.csv', sep=';',
                                                           index_col='Unnamed: 0')
                        if timeseries_evaluation:
                            df_scaled_mse_ticker = pd.read_csv('data/intermediary/df_scaled_mse_' + str(d) + '_' + column + '.csv',
                                                               sep=';')

                        if i == 0:
                            if timeseries_forecasting:
                                df_result = pd.DataFrame(index=df_result_ticker.index)

                            if timeseries_evaluation:
                                df_scaled_mse = pd.DataFrame()

                        if timeseries_forecasting:
                            df_result = df_result.join(df_result_ticker)
                        if timeseries_evaluation:
                            df_scaled_mse = pd.concat([df_scaled_mse, df_scaled_mse_ticker])

                    except:
                        print('file not available')

                if timeseries_forecasting:
                    df_result.to_csv('data/df_result_' + str(d) + '.csv', sep=';')
                if timeseries_evaluation:
                    df_scaled_mse.to_csv('data/df_scaled_mse_' + str(d) + '.csv', sep=';')

    # End of for loops
    # 3. Calculating stock risk for portfolio diversification
    # 4.Portfolio optimization using linear programming
    if portfolio_optimization:
        portfolio_results = []
        markowitz_allocation = []
        df_results_markowitz_allocation = pd.DataFrame()
        df_results_portfolio = pd.DataFrame()
        new_columns = []

        budget = 100000
        hidden_layers_latent = 20
        target_annual_return = 0.50

        for d in range(int(backtest_days / n_forecast) + 1)[::-1]:
            if d != 0:
                print('-' * 5 + 'Backtest Iteration ' + str(d))
                try:

                    portfolio_results_temp = []

                    # get full dataset
                    df_original = pd.read_csv('data/historical_stock_prices_original.csv', sep=';')
                    df_original.index = pd.to_datetime(df_original.date)

                    # get backtest iteration dataset with forecasted values
                    df_result = pd.read_csv('data/df_result_' + str(d) + '.csv', sep=';', index_col='Unnamed: 0',
                                            parse_dates=True)

                    ## Deep Portfolio
                    print('-' * 15 + 'PART IV: Autoencoder Deep Portfolio Optimization')
                    print('-' * 20 + 'Create dataset')
                    df_result_close = df_result.filter(like='Close', axis=1)
                    df_original_close_full = df_original.filter(like='Close', axis=1)

                    new_columns = []
                    [new_columns.append(c.split('_')[0]) for c in df_result_close.columns ]
                    df_result_close.columns = new_columns

                    new_columns = []
                    [new_columns.append(c.split('_')[0]) for c in df_original_close_full.columns ]
                    df_original_close_full.columns = new_columns
                    df_original_close = df_original_close_full.iloc[:, :number_of_stocks]

                    print('-' * 20 + 'Data Cleaning: Check if all values are positive')
                    try:
                        assert len(df_result_close[df_result_close >= 0].dropna(axis=1).columns) == len(df_result_close.columns)
                    except Exception as exception:
                        # Output unexpected Exceptions.
                        print('Dataframe contains negative and zero numbers. Replacing them with 0')
                        df_result_close = df_result_close[df_result_close >= 0].dropna(axis=1)

                    try:
                        assert len(df_original_close[df_original_close >= 0].dropna(axis=1).columns) == len(df_original_close.columns)
                    except Exception as exception:
                        # Output unexpected Exceptions.
                        print('Dataframe contains negative and zero numbers. Replacing them with 0')
                        df_original_close = df_original_close[df_original_close >= 0].dropna(axis=1)

                    print('-' * 20 + 'Transform dataset')
                    df_pct_change = df_result_close.pct_change(1).astype(float)
                    df_pct_change = df_pct_change.replace([np.inf, -np.inf], np.nan)
                    df_pct_change = df_pct_change.fillna(method='ffill')
                    # the percentage change function will make the first two rows equal to nan
                    df_pct_change = df_pct_change.tail(len(df_pct_change) - 2)

                    df_pct_change_original = df_original_close.pct_change(1).astype(float)
                    df_pct_change_original = df_pct_change_original.replace([np.inf, -np.inf], np.nan)
                    df_pct_change_original = df_pct_change_original.fillna(method='ffill')
                    # the percentage change function will make the first two rows equal to nan
                    df_pct_change_original = df_pct_change_original.tail(len(df_pct_change_original) - 2)

                    # -------------------------------------------------------
                    #           Step2: Variational Autoencoder Model
                    # -------------------------------------------------------
                    print('-' * 25 + 'Apply MinMax Scaler')
                    df_scaler = preprocessing.MinMaxScaler()
                    df_pct_change_normalised = df_scaler.fit_transform(df_pct_change)

                    print('-' * 25 + 'Define variables')
                    x = np.array(df_pct_change_normalised)
                    input_dim = x.shape[1]
                    timesteps = x.shape[0]

                    print('-' * 25 + 'Define Variational Autoencoder Model')
                    var_autoencoder, var_decoder, var_encoder = defineVariationalAutoencoder(original_dim = input_dim,
                                         intermediate_dim = 300,
                                         latent_dim= 1)

                    #plot_model(var_encoder, to_file='img/model_var_autoencoder_encoder.png', show_shapes=True,
                    #           show_layer_names=True)
                    #plot_model(var_decoder, to_file='img/model_var_autoencoder_decoder.png', show_shapes=True,
                    #           show_layer_names=True)

                    print('-' * 25 + 'Fit variational autoencoder model')
                    var_autoencoder.fit(x, x, callbacks=callbacks_list,  batch_size=64, epochs=epochs, verbose=verbose)
                    reconstruct = var_autoencoder.predict(x, batch_size=batch_size)

                    print('-' * 25 + 'Inverse transform dataset with MinMax Scaler')
                    reconstruct_real = df_scaler.inverse_transform(reconstruct)
                    df_var_autoencoder_reconstruct_real = pd.DataFrame(data=reconstruct_real, columns=df_pct_change.columns)

                    print('-' * 25 + 'Calculate L2 norm as reconstruction loss metric')
                    df_recreation_error = getReconstructionErrorsDF(df_pct_change=df_pct_change
                                                                    , reconstructed_data=reconstruct_real)
                    df_var_autoencoder_reconstruct_real_cov = df_var_autoencoder_reconstruct_real.cov()

                    # -------------------------------------------------------
                    #           Step2: Similarity Model
                    # -------------------------------------------------------

                    print('-' * 20 + 'Step 2 : Returns vs. latent feature similarity')
                    print('-' * 25 + 'Transpose dataset')

                    # change if original dataset should be used instead o cleaned version
                    df_latent_feature_input =  df_pct_change
                    df_pct_change_transposed = df_latent_feature_input.transpose()

                    print('-' * 25 + 'Transform dataset with MinMax Scaler')
                    df_scaler = preprocessing.MinMaxScaler()
                    df_pct_change_transposed_normalised = df_scaler.fit_transform(df_pct_change_transposed)

                    # define autoencoder
                    print('-' * 25 + 'Define autoencoder model')
                    num_stock = len(df_pct_change_transposed.columns)
                    autoencoderTransposed = defineAutoencoder(num_stock=num_stock, encoding_dim=hidden_layers_latent,
                                                              verbose=verbose)

                    # train autoencoder
                    print('-' * 25 + 'Train autoencoder model')
                    autoencoderTransposed.fit(df_pct_change_transposed_normalised, df_pct_change_transposed_normalised,
                                              shuffle=False, epochs=epochs, batch_size=batch_size, verbose=verbose)

                    # Get the latent feature vector
                    print('-' * 25 + 'Get the latent feature vector')
                    autoencoderTransposedLatent = Model(inputs=autoencoderTransposed.input,
                                                        outputs=autoencoderTransposed.get_layer('Encoder_Input').output)
                    #plot_model(autoencoderTransposedLatent, to_file='img/model_autoencoder_2.png', show_shapes=True,
                    #           show_layer_names=True)

                    # predict autoencoder model
                    print('-' * 25 + 'Predict autoencoder model')
                    latent_features = autoencoderTransposedLatent.predict(df_pct_change_transposed_normalised)

                    print('-' * 25 + 'Calculate L2 norm as similarity metric')
                    df_similarity = getLatentFeaturesSimilariryDF(df_pct_change=df_latent_feature_input
                                                                  , latent_features=latent_features
                                                                  ,sorted = False)

                    df_latent_feature = pd.DataFrame(latent_features.T, columns=df_latent_feature_input.columns)
                    #df_similarity_delta = calc_delta_matrix(df_latent_feature.transpose())
                    # the smaller the value, the closer the stocks are related
                    df_similarity_delta = calc_delta_matrix(df_similarity['similarity_score'].transpose())
                    df_similarity_cov = df_latent_feature.cov()

                    # normalize between 0 and 1
                    min = np.min(df_similarity_cov)
                    max = np.max(df_similarity_cov)
                    df_similarity_cov_normalized = (df_similarity_cov - min) / ( max-min)


                    # calculate covariance matrix of stocks
                    df_pct_change_cov = df_pct_change.cov()

                    '''
                    # plots for 1. Selection of least volatile stocks using autoencoder latent feature value
                    if plot_results:
                        stable_stocks = False
                        unstable_stocks = True
                        plot_original_values = False
                        plot_delta_values = True
                        number_of_stable_unstable_stocks = 20
    
    
                        df_stable_stocks = df_recreation_error.sort_values(by=['recreation_error'], ascending=True).head(number_of_stable_unstable_stocks)
                        df_stable_stocks['recreation_error_class'] =  'top ' + str(number_of_stable_unstable_stocks)
                        l_stable_stocks = np.array(df_stable_stocks.head(number_of_stable_unstable_stocks).index)
    
                        plt.figure(figsize=(11, 6))
                        plt.box(False)
                        for stock in df_stable_stocks.index:
                            plt.plot(df_pct_change.head(500).index, df_pct_change[stock].head(500), label=stock)
    
                        plt.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                        plt.title('Top ' + str(number_of_stable_unstable_stocks) + ' most stable stocks based on recreation error')
                        plt.xlabel("Dates")
                        plt.ylabel("Returns")
                        plt.show()
    
    
    
                        df_unstable_stocks = df_recreation_error.sort_values(by=['recreation_error'], ascending=False).head(number_of_stable_unstable_stocks)
                        df_unstable_stocks['recreation_error_class'] = 'bottom ' + str(number_of_stable_unstable_stocks)
                        print(df_unstable_stocks.head(5))
                        l_unstable_stocks = np.array(df_unstable_stocks.head(number_of_stable_unstable_stocks).index)
    
                        # plot unstable stocks
                        plt.figure(figsize=(11, 6))
                        plt.box(False)
                        for stock in df_unstable_stocks.index:
                            plt.plot(df_pct_change.head(500).index, df_pct_change[stock].head(500), label=stock)
    
                        plt.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                        plt.title('Top ' + str(number_of_stable_unstable_stocks) + ' most unstable stocks based on recreation error')
                        plt.xlabel("Dates")
                        plt.ylabel("Returns")
                        plt.show()
    
                        if stable_stocks:
                            print('Plotting stable stocks')
                            list = l_stable_stocks
                            title = 'Original versus autoencoded stock price for low recreation error (stable stocks)'
    
                        if unstable_stocks:
                            print('Plotting unstable stocks')
                            list = l_unstable_stocks
                            title = 'Original versus autoencoded stock price for high recreation error (unstable stocks)'
    
    
                        plt.figure()
                        plt.rcParams["figure.figsize"] = (8, 14)
                        plt.title(title, y=1.08)
                        plt.box(False)
                        fig, ax = plt.subplots(len(list), 1)
    
                        i = 0
                        for stock in list:
                            which_stock = df_result_close.columns.get_loc(stock)
                            which_stock_name = df_result_close.columns[which_stock,]
    
                            ## plot for comparison
                            if plot_original_values:
    
                                stock_autoencoder_1 = convert_relative_changes_to_absolute_values(
                                    relative_values=df_reconstruct_real[stock], initial_value=df_result_close.iloc[
                                        2, which_stock])  # the initial value is the second one as the first one is nan because of the delta calculation
    
                                print('Plotting original values')
                                ax[i].plot(df_result_close.iloc[2:, which_stock])
                                ax[i].plot(df_result_close.index[2:], stock_autoencoder_1[:])
    
                            if plot_delta_values:
                                print('Plotting delta values')
                                ax[i].plot(df_pct_change[stock])
                                ax[i].plot(df_pct_change.index[:], df_reconstruct_real[stock])
    
                            ax[i].legend(['Original ' + str(which_stock_name), 'Autoencoded ' + str(which_stock_name)],
                                         frameon=False)
    
                            # set title
                            # plt.set_title('Original stock price [{}] versus autoencoded stock price '.format(column), fontsize=fontsize)
                            ax[i].spines['top'].set_visible(False)
                            ax[i].spines['right'].set_visible(False)
                            ax[i].spines['left'].set_visible(False)
                            ax[i].spines['bottom'].set_visible(False)
                            ax[i].axes.get_xaxis().set_visible(False)
    
                            i = i + 1
    
                        plt.xticks(fontsize=fontsize)
                        plt.yticks(fontsize=fontsize)
                        plt.show()
    
                        # Plots for 3. Calculating stock risk for portfolio diversification
                        least_similar_stocks = False
                        most_similar_stocks = True
    
                        example_stock_names = df_pct_change.columns  # 'AMZN'
                        for example_stock_name in example_stock_names[0:30]:
    
                            example_stock_name =  'GOOGL' #'MSFT'#'AAPL'#'AMZN' #
                            top_n = 10
    
                            df_pct_change_corr_most_example = df_pct_change_corr[[example_stock_name]].sort_values(
                                by=[example_stock_name], ascending=False).head(top_n)
                            df_pct_change_corr_least_example = df_pct_change_corr[[example_stock_name]].sort_values(
                                by=[example_stock_name], ascending=False).tail(top_n)
    
                            df_similarity_most_example = df_similarity_cor[[example_stock_name]].sort_values(
                                by=[example_stock_name],
                                ascending=False).head(top_n)
                            df_similarity_least_example = df_similarity_cor[[example_stock_name]].sort_values(
                                by=[example_stock_name],
                                ascending=False).tail(top_n)
    
    
    
                            least_stock_cv = df_pct_change_corr_least_example.head(1).index.values[0]
                            most_stock_cv = df_pct_change_corr_most_example.iloc[[1]].index.values[0]
    
                            least_stock_ae = df_similarity_least_example.head(1).index.values[0]
                            most_stock_ae = df_similarity_most_example.iloc[[1]].index.values[0]
    
    
    
    
                            # Plot original series for comparison
                            plt.figure()
                            plt.rcParams["figure.figsize"] = (18, 10)
                            plt.box(False)
                            fig, ((ax1, ax2),(ax3, ax4 ), (ax5,ax6)) = plt.subplots(3, 2)
                            #fig.tight_layout(pad=10.0)
                            fig.suptitle('Baseline stock: ' + example_stock_name + ' compared to least (left) and most (right) related stocks', y=1)
    
                            ax1.plot(df_result_close.index, df_result_close[example_stock_name], label=example_stock_name)
                            ax1.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax1.spines['top'].set_visible(False)
                            ax1.spines['right'].set_visible(False)
                            ax1.spines['left'].set_visible(False)
                            ax1.spines['bottom'].set_visible(False)
    
                            ax3.plot(df_result_close.index, df_result_close[least_stock_cv], label=least_stock_cv + '(covariance)')
                            ax3.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax3.spines['top'].set_visible(False)
                            ax3.spines['right'].set_visible(False)
                            ax3.spines['left'].set_visible(False)
                            ax3.spines['bottom'].set_visible(False)
    
                            ax5.plot(df_result_close.index, df_result_close[least_stock_ae], label=least_stock_ae + '(latent feature)')
                            ax5.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax5.spines['top'].set_visible(False)
                            ax5.spines['right'].set_visible(False)
                            ax5.spines['left'].set_visible(False)
                            ax5.spines['bottom'].set_visible(False)
    
                            ax2.plot(df_result_close.index, df_result_close[example_stock_name], label=example_stock_name)
                            ax2.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax2.spines['top'].set_visible(False)
                            ax2.spines['right'].set_visible(False)
                            ax2.spines['left'].set_visible(False)
                            ax2.spines['bottom'].set_visible(False)
    
                            ax4.plot(df_result_close.index, df_result_close[most_stock_cv],
                                     label=most_stock_cv + '(covariance)')
                            ax4.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax4.spines['top'].set_visible(False)
                            ax4.spines['right'].set_visible(False)
                            ax4.spines['left'].set_visible(False)
                            ax4.spines['bottom'].set_visible(False)
    
                            ax6.plot(df_result_close.index, df_result_close[most_stock_ae],
                                     label=most_stock_ae + '(latent feature)')
                            ax6.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax6.spines['top'].set_visible(False)
                            ax6.spines['right'].set_visible(False)
                            ax6.spines['left'].set_visible(False)
                            ax6.spines['bottom'].set_visible(False)
    
                            plt.xlabel("Dates")
                            plt.ylabel("Stock Value")
                            plt.show()
    
    
    
                            # Plots for 3. compare original timeseries with latent features
                            plt.figure()
                            plt.rcParams["figure.figsize"] = (18, 10)
                            plt.box(False)
                            fig, ((ax1),(ax2)) = plt.subplots(2, 1)
                            # fig.tight_layout(pad=10.0)
                            fig.suptitle(
                                'Orignal stock (top): ' + example_stock_name + ' compared to least (left) and most (right) related stocks',
                                y=1)
        
                            ax1.plot(df_pct_change.index, df_pct_change[example_stock_name], label=example_stock_name)
                            ax1.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax1.spines['top'].set_visible(False)
                            ax1.spines['right'].set_visible(False)
                            ax1.spines['left'].set_visible(False)
                            ax1.spines['bottom'].set_visible(False)
        
                            ax2.plot(df_latent_feature.index, df_latent_feature[example_stock_name], label=example_stock_name)
                            ax2.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
                            # removing all borders
                            ax2.spines['top'].set_visible(False)
                            ax2.spines['right'].set_visible(False)
                            ax2.spines['left'].set_visible(False)
                            ax2.spines['bottom'].set_visible(False)
        
                            plt.xlabel("Dates")
                            plt.ylabel("Stock Value")
                            plt.show()
                       
    
                '''

                    # -------------------------------------------------------
                    #           Step3: Markowitz Model
                    # -------------------------------------------------------

                    print('-' * 20 + 'Step 3: Create dataset')
                    df_result_close = df_result_close[df_pct_change.columns]

                    print('-' * 20 + 'Step 3: Markowitz model without forecast values and without preselection')
                    discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                          df=df_original_close.head(len(df_original_close) - n_forecast * d)
                        , budget=budget
                        , S=df_pct_change_original.cov()
                        , type='max_sharpe'
                        , target=target_annual_return)

                    df_markowitz_allocation_without_forecast_without_preseletcion = pd.DataFrame(
                        discrete_allocation.items(),
                        columns=['stock_name', 'bought_volume_without_forecast_without_preselection'])
                    df_markowitz_allocation_without_forecast_without_preseletcion = df_markowitz_allocation_without_forecast_without_preseletcion.set_index(
                        'stock_name')

                    append_to_portfolio_results(array=portfolio_results_temp,
                                                d=d,
                                                portfolio_type='markowitz_portfolio_without_forecast_without_preselection',
                                                discrete_allocation=discrete_allocation,
                                                results=results)

                    print('-' * 20 + 'Step 3: Markowitz model without forecast values')
                    discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                        df=df_result_close.head(len(df_result_close) - n_forecast)
                        , budget=budget
                        , S=df_pct_change_cov
                        , type='max_sharpe'
                        , target=target_annual_return)
                    df_markowitz_allocation_without_forecast = pd.DataFrame(discrete_allocation.items(),
                                                                            columns=['stock_name',
                                                                                     'bought_volume_without_forecast'])
                    df_markowitz_allocation_without_forecast = df_markowitz_allocation_without_forecast.set_index(
                        'stock_name')

                    append_to_portfolio_results(array=portfolio_results_temp,
                                                d=d,
                                                portfolio_type='markowitz_portfolio_without_forecast',
                                                discrete_allocation=discrete_allocation,
                                                results=results)

                    print('-' * 20 + 'Step 3: Markowitz model with forecast')
                    discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                        df=df_result_close
                        , budget=budget
                        , S=df_pct_change_cov
                        , type='max_sharpe'
                        , target=target_annual_return)
                    df_markowitz_allocation_with_forecast = pd.DataFrame(discrete_allocation.items(),
                                                                         columns=['stock_name',
                                                                                  'bought_volume_with_forecast'])
                    df_markowitz_allocation_with_forecast = df_markowitz_allocation_with_forecast.set_index(
                        'stock_name')

                    append_to_portfolio_results(array=portfolio_results_temp,
                                                d=d,
                                                portfolio_type='markowitz_portfolio_with_forecast',
                                                discrete_allocation=discrete_allocation,
                                                results=results)

                    # cla = CLA(expected_returns=mu, cov_matrix=S, weight_bounds=(0, 1))
                    # Plotting.plot_efficient_frontier(cla, points=100, show_assets=True)

                    print('-' * 20 + 'Step 3: Markowitz model with cleaned covariance matrix')
                    discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                          df=df_result_close
                        , budget=budget
                        , S=df_var_autoencoder_reconstruct_real_cov
                        , type='max_sharpe'
                        , target=target_annual_return
                        , cov_type='adjusted')
                    df_markowitz_allocation_var_autoencoder = pd.DataFrame(discrete_allocation.items(),
                                                                           columns=['stock_name',
                                                                                    'bought_volume_with_forecast_cleaned'])
                    df_markowitz_allocation_var_autoencoder = df_markowitz_allocation_var_autoencoder.set_index(
                        'stock_name')

                    append_to_portfolio_results(array=portfolio_results_temp,
                                                d=d,
                                                portfolio_type='markowitz_portfolio_with_forecast_and adjusted covariance_matrix',
                                                discrete_allocation=discrete_allocation,
                                                results=results)

                    print('-' * 20 + 'Step 3: Markowitz model with latent features')
                    gamma = 0.1

                    ''''
                    1. df_similarity_cov_normalized[1,2] > df_similarity_cov_normalized[1,3] --> stock 1 and 2 is more similar than stock 1 and 3
                    2. S= df_pct_change_cov * df_similarity_cov_normalized and df_pct_change_cov[1,2]=df_pct_change_cov[1,3] --> S[1,2] > S[1,3]
                    3. min(S) --> S[1,3] will be considered during optimization more likely then S[1,2] -->  penalize similar stocks more than non-similar stocks
                    
                    '''

                    try:
                        discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                            df=df_result_close
                            , budget=budget
                             ,S = df_pct_change_cov * df_similarity_cov_normalized
                            , type='max_sharpe'
                            , target=target_annual_return
                            , cov_type='adjusted')
                    except RuntimeWarning:
                        print('RuntimeWarning: invalid value encountered in sqrt sigma = np.sqrt(np.dot(weights, np.dot(cov_matrix, weights.T)))')
                        discrete_allocation, discrete_leftover, weights, cleaned_weights, mu, S, results = calcMarkowitzPortfolio(
                            df=df_result_close
                            , budget=budget
                            , S=df_pct_change_cov
                            , type='max_sharpe'
                            , target=target_annual_return
                            , cov_type='adjusted')


                    df_markowitz_allocation_latent_feature = pd.DataFrame(discrete_allocation.items(),
                                                                          columns=['stock_name',
                                                                                   'bought_volume_with_forecast_latent'])
                    df_markowitz_allocation_latent_feature = df_markowitz_allocation_latent_feature.set_index(
                        'stock_name')

                    append_to_portfolio_results(array=portfolio_results_temp,
                                                d=d,
                                                portfolio_type='markowitz_portfolio_with_forecast_and_latent_features',
                                                discrete_allocation=discrete_allocation,
                                                results=results)

                    df_markowitz_allocation = df_markowitz_allocation_without_forecast_without_preseletcion.join(
                        df_markowitz_allocation_with_forecast
                        , how='outer'
                        , lsuffix=''
                        , rsuffix='')
                    df_markowitz_allocation = df_markowitz_allocation.join(df_markowitz_allocation_without_forecast
                                                                           , how='outer'
                                                                           , lsuffix=''
                                                                           , rsuffix='')
                    df_markowitz_allocation = df_markowitz_allocation.join(df_markowitz_allocation_var_autoencoder
                                                                           , how='outer'
                                                                           , lsuffix=''
                                                                           , rsuffix='')

                    df_markowitz_allocation = df_markowitz_allocation.join(df_markowitz_allocation_latent_feature
                                                                           , how='outer'
                                                                           , lsuffix=''
                                                                           , rsuffix='')

                    df_result_close_buy_price = df_original_close.tail(n_forecast * d).head(1).transpose()
                    df_result_close_buy_price = df_result_close_buy_price.rename(
                        columns={df_result_close_buy_price.columns[0]: "buy_price"})

                    df_result_close_predicted_price = df_original_close.tail(1).transpose()
                    df_result_close_predicted_price = df_result_close_predicted_price.rename(
                        columns={df_result_close_predicted_price.columns[0]: "predicted_price"})

                    df_result_close_sell_price = df_original_close.head(len(df_original_close) - n_forecast * (d - 1))
                    df_result_close_sell_price = df_result_close_sell_price.tail(1).transpose()
                    df_result_close_sell_price = df_result_close_sell_price.rename(
                        columns={df_result_close_sell_price.columns[0]: "sell_price"})

                    df_markowitz_allocation = df_markowitz_allocation.join(df_result_close_buy_price, how='left')
                    df_markowitz_allocation = df_markowitz_allocation.join(df_result_close_predicted_price, how='left')
                    df_markowitz_allocation = df_markowitz_allocation.join(df_result_close_sell_price, how='left')
                    df_markowitz_allocation['backtest_id'] = d

                    df_markowitz_allocation['delta'] = df_markowitz_allocation['sell_price'] - df_markowitz_allocation[
                        'buy_price']

                    df_markowitz_allocation['profit_without_forecast_without_preselection'] = df_markowitz_allocation[
                                                                                                  'delta'] * \
                                                                                              df_markowitz_allocation[
                                                                                                  'bought_volume_without_forecast_without_preselection']
                    df_markowitz_allocation['profit_without_forecast'] = df_markowitz_allocation['delta'] * \
                                                                         df_markowitz_allocation[
                                                                             'bought_volume_without_forecast']
                    df_markowitz_allocation['profit_with_forecast'] = df_markowitz_allocation['delta'] * \
                                                                      df_markowitz_allocation[
                                                                          'bought_volume_with_forecast']
                    df_markowitz_allocation['profit_with_forecast_cleaned'] = df_markowitz_allocation['delta'] * \
                                                                              df_markowitz_allocation[
                                                                                  'bought_volume_with_forecast_cleaned']
                    df_markowitz_allocation['profit_with_forecast_latent'] = df_markowitz_allocation['delta'] * \
                                                                             df_markowitz_allocation[
                                                                                 'bought_volume_with_forecast_latent']

                    df_results_markowitz_allocation = df_results_markowitz_allocation.append(df_markowitz_allocation)

                    df_results_portfolio_temp = pd.DataFrame.from_dict(portfolio_results_temp)

                    df_results_portfolio_temp['profit'] = [
                        np.sum(df_markowitz_allocation['profit_without_forecast_without_preselection']),
                        np.sum(df_markowitz_allocation['profit_without_forecast'])
                        , np.sum(df_markowitz_allocation['profit_with_forecast'])
                        , np.sum(df_markowitz_allocation['profit_with_forecast_cleaned'])
                        , np.sum(df_markowitz_allocation['profit_with_forecast_latent'])
                    ]

                    # append to final dataset
                    df_results_portfolio = df_results_portfolio.append(df_results_portfolio_temp)
                    # End of for loop

                except:
                    print('file does not exists')

                df_results_portfolio.to_csv('df_backtest_portfolio.csv', sep=';',
                                            columns=df_results_portfolio_temp.columns)


                df_results_portfolio_used = pd.read_csv('df_backtest_portfolio.csv', sep=';')
                df_results_portfolio_used = df_results_portfolio_used[df_results_portfolio_temp.columns]
                df_results_portfolio_used = df_results_portfolio_used[df_results_portfolio_used['portfolio_type'] != 'markowitz_portfolio_without_forecast_without_preselection' ]
                df_results_portfolio_used = df_results_portfolio_used[df_results_portfolio_used['portfolio_type'] != 'markowitz_portfolio_with_forecast_and adjusted covariance_matrix']

                volatility_10 = []
                volatility_252 = []
                for backtest in df_results_portfolio_used['backtest_iteration'].unique():
                    print('Calculating portfolio annual volatility for backtest {v_backtest}'.format(v_backtest =str(backtest)))
                    df_original_backtest = df_original_close_full.head(len(df_original_close_full) - n_forecast * (backtest - 1))
                    for portfolio_type in df_results_portfolio_used['portfolio_type'].unique():
                        selected_stocks = \
                        df_results_portfolio_used[(df_results_portfolio_used['backtest_iteration'] == backtest)
                                                  & (df_results_portfolio_used['portfolio_type'] == portfolio_type)][
                            'discrete_allocation'].values

                        selected_stocks_json = json.loads(selected_stocks[0].replace("\'", "\""))
                        stocks = []
                        weights = []
                        for stock in selected_stocks_json:
                            stocks.append(stock)
                            weights.append(selected_stocks_json[stock])

                        weights = weights / np.sum(weights)
                        data = df_original_backtest[stocks]
                        log_returns = data.pct_change()
                        portfolio_vol_252 = np.sqrt(np.dot(weights.T, np.dot(log_returns.cov() * 252, weights)))
                        portfolio_vol_10 = np.sqrt(np.dot(weights.T, np.dot(log_returns.cov() * 10, weights)))
                        volatility_252.append(portfolio_vol_252)
                        volatility_10.append(portfolio_vol_10)

                df_volatility = pd.DataFrame(volatility_252, columns=['portfolio_volatility_252'])
                df_volatility['portfolio_volatility_10'] = volatility_10
                df_results_portfolio_used_with_volatility = df_results_portfolio_used.join(df_volatility, how='left')
                df_results_portfolio_used_with_volatility['cumsum_profit'] = df_results_portfolio_used_with_volatility.groupby('portfolio_type')['profit'].cumsum()
                df_results_portfolio_used_with_volatility['10_expected_return'] = df_results_portfolio_used_with_volatility['profit']/budget
                df_results_portfolio_used_with_volatility['sharpe_ratio_10'] = df_results_portfolio_used_with_volatility['10_expected_return']\
                                                                               /df_results_portfolio_used_with_volatility['portfolio_volatility_10']

                # Plot
                colors = ['#2195ca' ,'#c1c1c1','#f9c77d'] # blue, grey, yellow
                plot_backtest_results(df_results_portfolio_used_with_volatility, column='profit',  colors =  colors)
                plot_backtest_results(df_results_portfolio_used_with_volatility, column='cumsum_profit',  colors =  colors)
                #plot_backtest_results(df_results_portfolio_used_with_volatility, column='portfolio_volatility_10',  colors =  colors)
                #plot_backtest_results(df_results_portfolio_used_with_volatility, column='portfolio_volatility_252',  colors =  colors)
                plot_backtest_results(df_results_portfolio_used_with_volatility, column='expected_annual_return',  colors =  colors)
                #plot_backtest_results(df_results_portfolio_used_with_volatility, column='sharpe_ratio_10',  colors =  colors)
                plot_backtest_results(df_results_portfolio_used_with_volatility, column='sharpe_ratio',  colors =  colors)
                plot_backtest_results(df_results_portfolio_used_with_volatility, column='annual_volatility',  colors =  colors)




