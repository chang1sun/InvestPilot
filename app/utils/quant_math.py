import pandas as pd

def calculate_indicators(data_list):
    """
    Calculate technical indicators (MA, RSI) for the K-line data.
    """
    if not data_list:
        return []
        
    df = pd.DataFrame(data_list)
    
    # Moving Averages
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Fill NaNs
    df.fillna(0, inplace=True)
    
    # Convert back to list of dicts, keeping original fields plus indicators
    return df.to_dict('records')

