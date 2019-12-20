from pathlib import Path

import pandas as pd
import numpy as np
import pandas_profiling

if __name__ == "__main__":
    df = pd.read_csv(
        "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"
    )
    df['Index'] = np.where(df.Sex == 'male', 1, 0)
    profile = df.profile_report(title="Titanic Dataset", feature_index = 'Index')
    #profile.to_file(output_file=Path("./titanic_report.html"))
