import numpy as np
import pandas as pd
from itertools import repeat
from jellyfish import jaro_winkler as jw
from multiprocessing import cpu_count, Pool


def match_names(df1,df2,col1,col2):
    '''
    Takes in two dataframes and a column name from each, standardizes the values
    in the two columns, and returns a dataframe of the Cartesian product of the
    dataframes with the Jaro-Winkler similarity of the values in the columns.
    '''

    df1[col1] = df1[col1].apply(stdname)
    df2[col2] = df2[col2].apply(stdname)

    prod = cart_prod(df1,df2)

    jws = jwsim(prod,col1,col2)

    return jws


def cart_prod(df1,df2):
    '''
    Takes the Cartesian product of two different dataframes (for which column
    names do not overlap). Returns a dataframe.
    '''

    k = 'key'

    # In each df, create a key column with all the same values
    df1 = df1.assign(key=0)
    df2 = df2.assign(key=0)

    print('Taking a Cartesian product')

    # Take the Cartesian product of the two dataframes
    prod = pd.merge(df1,df2,on=k)

    # Drop the added column
    prod = prod.drop(k,axis=1)

    return prod


def jwsim(args):
    '''
    TAKES A SINGLE PARAMETER, A TUPLE of a dataframe and a tuple of colnames.
    Caclulates the Jaro-Winkler similarity between the two specified columns of
    the given dataframe. Returns a dataframe.
    '''

    df, cols = args
    col1, col2 = cols

    print('.')

    df['JWSimilarity'] = df.apply(lambda x: jw(x[col1],x[col2]),axis=1)

    return df


def parallelize(function,tuple):
    '''
    Adapted from http://blog.adeel.io/2016/11/06/parallelize-pandas-map-or-apply

    Parallelizes function, which is called on the parts of tuple (which are,
    respectively, the dataframe and the two columns on which the function will
    be called).
    '''
    df,col1,col2 = tuple
    cores = cpu_count()
    partitions = cores * 4
    data_split = np.array_split(df, partitions)
    pool = Pool(cores)
    data = pd.concat(pool.map(function, zip(data_split,repeat((col1,col2)))))
    pool.close()
    pool.join()
    return data