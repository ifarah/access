import re
import UTILS as u
import numpy as np
import pandas as pd
import MATCH_NAMES as mn
import MERGE_CONTRACTS as mc
import IMPORT_ADDRESSES as ad
import AMOUNT_CALCULATIONS as ac
import ADDRESS_CLEANER as addclean
from STANDARDIZE_NAME import standardize_name as stdname

# Minimum Jaro-Winkler similarity required to deem two strings a match
JWSIM_THRESH = .9

# Minimum dollar amount required to keep a contract record
MIN_DOLLARS = .01

# File shortcut
OUT = '../../../rcc-uchicago/PCNO/CSV/chicago/prehq_contracts.csv'


def read_contracts():
    '''
    Reads in the contracts dataset via the MERGE_CONTRACTS module. Returns a
    dataframe.
    '''

    # Initialize an empty list to hold the dataframes
    dfs = []

    # For every ((filename,label)) tuple:
    for fname_tuple in mc.FNAMES:
        # Read in and process the dataset
        df = mc.process_dataset(fname_tuple)
        # If the label == 'CHI':
        if fname_tuple[-1] == 'CHI':
            # Send the dataframe through the round2 address cleaner
            df = addclean.round2(df)
            # Send the Address1 field through the address cleaner
            df['Address1'] = df['Address1'].apply(addclean.address_cleaner)
        # Add the newly processed dataframe into the list
        dfs.append(df)

    # Concatenate all the dataframes
    merged = pd.concat(dfs)

    # Convert the text columns (except for the URLs) to uppercase
    merged = u.upper(merged)

    # There should be this many records in the dataframe:  6591 records
    return merged


def clean_amounts(df):
    '''
    Cleans dollar amounts with the clean_dollars function, then drops contracts
    with amounts below the MIN_DOLLARS threshold. Returns a dataframe.
    '''

    print('Cleaning amounts')

    # Shortcut
    a = 'Amount'

    # Call the clean_dollars function on the Amount column
    df[a] = df[a].apply(ac.clean_dollars)

    # Drop amounts below the minimum threshold
    df = ac.drop_low(df,MIN_DOLLARS)

    return df


def import_addresses(dataset):
    '''
    Reads in one of three address datasets (specified with a string). Returns a
    dataframe.
    '''

    print('Reading in {} addresses'.format(dataset.upper()))

    # Read in the COOK address dataset; rename a column
    if dataset == 'cook':
        df = ad.read_cook_addr()
        df = df.rename(columns={'ID':'VendorName'},index=str)

    # Read in the IRS dataset; rename a column and standardize names
    elif dataset == 'irs':
        df = ad.read_irs()
        df = df.rename(columns={'OrganizationName':'VendorName'},index=str)
        df['VendorName'] = df['VendorName'].apply(stdname)

    # Read in the IL address dataset; standardize names
    elif dataset == 'il':
        df = ad.read_il_addr()
        df['VendorName'] = df['VendorName'].apply(stdname)

    # Conver text fields to uppercase
    df = u.upper(df)

    return df


def jwsim_contracts_irs(contracts,irs,suffix):
    '''
    Takes the contracts and IRS dataframes and returns a dataframe of records
    with matching names where the JW similarity is >= JWSIM_THRESH.
    '''

    # Rename the columns in IRS:
    irs = u.rename_cols(irs,irs.columns,suffix)

    # Restrict the contracts df to just those from IL
    contracts = contracts[contracts.CSDS_Contract_ID.str.startswith('IL')]

    # Take the cartesian product between the two; replace np.NaN with ''
    prod = mn.cart_prod(contracts,irs)
    prod = prod.replace(np.NaN,'')

    # Print progress report
    print('Calculating Jaro-Winkler similarity on vendor names')

    # Compute the Jaro-Winkler similarity on the VendorName cols
    col1 = 'VendorName'
    arg = ((prod,col1,col1 + suffix))
    jwsim = mn.parallelize(mn.jwsim,arg)

    # Return only the rows where JW similarity >= JWSIM_THRESH
    return jwsim[jwsim.JWSimilarity >= JWSIM_THRESH]


def coalesce_matches(contracts,jwsim,suffix):
    '''
    Pulls in the addresses from IRS records previously deemed to match the IL
    agencies. Returns a dataframe.
    '''

    jwsim = trim_jwsim(jwsim,suffix)

    # Define the key on which to coalesce
    keys = ['CSDS_Contract_ID']

    # Fill in missing values in contracts from matches in jwsim, matchin on keys
    df = u.merge_coalesce(contracts,jwsim,keys,suffix)

    return df


def trim_jwsim(jwsim,suffix):
    '''
    Trims off the original columns that were duplicated in the matching process
    as well as filtering out multiple matches per contract. Returns a dataframe.
    '''

    # Take the top match per contract
    jwsim = jwsim.sort_values('JWSimilarity',ascending=False)
    jwsim = jwsim.drop_duplicates(subset='CSDS_Contract_ID',keep='first')

    # Rename two columns that must be retained in the next step
    cn = {'VendorName_IRS':'IRSOrgName','CSDS_Org_ID_IRS':'CSDS_Org_ID'}
    jswim = jwsim.rename(columns=cn,index=str)

    # Keep only these cols
    keep = ['CSDS_Contract_ID'] + [x for x in jwsim.columns if 'IRS' in x]
    jwsim = jwsim[keep]

    # Make a dictionary of old to new names (stripping the suffix)
    old = [x for x in jwsim.columns if x.endswith(suffix)]
    new = [re.sub(suffix + '$','',x) for x in old]
    names = dict(zip(old,new))

    # Rename the columns as specified in the dictionary
    jwsim = jwsim.rename(columns=names,index=str)

    return jwsim


def preprocess_contracts():
    '''
    Reads in the contract records. Preprocesses them to clean the amounts and
    keep only those over the minimum amount specified in the MIN_DOLLARS
    constant.  Imports hand-collected addresses for Cook and IL contracts and
    merges in addresses from IRS990 forms to fill in as many blanks as possible.
    Returns a dataframe.
    '''

    # Read in the contracts and clean the dollar amounts
    contracts = read_contracts()
    contracts = clean_amounts(contracts)

    # Read in the COOK addresses dataset
    cook = import_addresses('cook')

    # Fill in addresses from the COOK dataset, matching on VendorName; then,
    # standardize VendorName
    print('Coalescing COOK address matches')
    merged = u.merge_coalesce(contracts,cook,'VendorName')
    merged['VendorName'] = merged['VendorName'].apply(stdname)

    # Read in the IRS dataset
    irs = import_addresses('irs')

    # Get a datframe of JW similarity matches >= JWSIM_THRESH between the merged
    # and irs dataframes
    sfx = '_IRS'
    jwsim = jwsim_contracts_irs(merged,irs,sfx)

    # Print progress report
    print('Coalescing IRS matches')

    # Fill in addresses from the IRS dataset
    coalesced = coalesce_matches(merged,jwsim,sfx)

    # Read in the IL addresses dataset
    il = import_addresses('il')

    # Print progress report
    print('Coalescing IL matches')

    # Fill in addresses from the IL dataset, matching on VendorName
    df = u.merge_coalesce(coalesced,il,'VendorName')

    return df


if __name__ == '__main__':

    df = preprocess_contracts()

    df.to_csv(OUT,index=False)
