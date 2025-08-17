import pandas as pd

df = pd.read_excel('cpe_extracted_data.xlsx')
false_entries = df[df['Validation Product Name'] == False]
false_entries.to_csv('output/false_entries.csv', index=False)