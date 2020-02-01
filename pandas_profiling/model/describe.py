"""Compute statistical description of datasets."""
import multiprocessing.pool
import multiprocessing
import itertools
import os
import warnings
from pathlib import Path
from typing import Tuple
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from astropy.stats import bayesian_blocks

from pandas_profiling.config import config as config
from pandas_profiling.model.messages import (
    check_variable_messages,
    check_table_messages,
    warning_type_date,
)

from pandas_profiling.model import base
from pandas_profiling.model.base import Variable
from pandas_profiling.model.correlations import (
    calculate_correlations,
    perform_check_correlation,
)
from pandas_profiling.utils.common import update
from pandas_profiling.view import plot


def describe_numeric_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a numeric series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.

    Notes:
        When 'bins_type' is set to 'bayesian_blocks', astropy.stats.bayesian_blocks is used to determine the number of
        bins. Read the docs:
        https://docs.astropy.org/en/stable/visualization/histogram.html
        https://docs.astropy.org/en/stable/api/astropy.stats.bayesian_blocks.html

        This method might print warnings, which we suppress.
        https://github.com/astropy/astropy/issues/4927
    """
    quantiles = config["vars"]["num"]["quantiles"].get(list)
    series1 = series.loc[list0]
    series2 = series.loc[list1]

    if config["compare_profile_analysis"].get(bool):
        stats = {
            "mean1": series1.mean(),
            "mean2": series2.mean(),
            "std1": series1.std(),
            "std2": series2.std(),
            "variance1": series1.var(),
            "variance2": series2.var(),
            "min1": series1.min(),
            "min2": series2.min(),
            "max1": series1.max(),
            "max2": series2.max(),
            "kurtosis1": series1.kurt(),
            "kurtosis2": series2.kurt(),
            "skewness1": series1.skew(),
            "skewness2": series2.skew(),
            "sum1": series1.sum(),
            "sum2": series2.sum(),
            "mad1": series1.mad(),
            "mad2": series2.mad(),
            "n_zeros1": (len(series1) - np.count_nonzero(series1)),
            "n_zeros2": (len(series2) - np.count_nonzero(series2)),
            "histogramdata1": series1,
            "histogramdata2": series2,
        }

        stats["range1"] = stats["max1"] - stats["min1"]
        stats["range2"] = stats["max2"] - stats["min2"]
        stats.update(
            {
                "{:.0%.1}".format(percentile): value
                for percentile, value in series1.quantile(quantiles).to_dict().items()
            }
        )

        stats.update(
            {
                "{:.0%.2}".format(percentile): value
                for percentile, value in series2.quantile(quantiles).to_dict().items()
            }
        )
        stats["iqr1"] = stats["75%.1"] - stats["25%.2"]
        stats["iqr2"] = stats["75%.1"] - stats["25%.2"]
        stats["cv1"] = stats["std1"] / stats["mean1"] if stats["mean1"] else np.NaN
        stats["cv2"] = stats["std2"] / stats["mean2"] if stats["mean2"] else np.NaN
        stats["p_zeros1"] = float(stats["n_zeros1"]) / len(series)
        stats["p_zeros2"] = float(stats["n_zeros2"]) / len(series)

    stats = {
        "mean": series.mean(),
        "std": series.std(),
        "variance": series.var(),
        "min": series.min(),
        "max": series.max(),
        "kurtosis": series.kurt(),
        "skewness": series.skew(),
        "sum": series.sum(),
        "mad": series.mad(),
        "n_zeros": (len(series) - np.count_nonzero(series)),
        "histogramdata": series,
    }

    stats["range"] = stats["max"] - stats["min"]
    stats.update(
        {
            "{:.0%}".format(percentile): value
            for percentile, value in series.quantile(quantiles).to_dict().items()
        }
    )
    stats["iqr"] = stats["75%"] - stats["25%"]
    stats["cv"] = stats["std"] / stats["mean"] if stats["mean"] else np.NaN
    stats["p_zeros"] = float(stats["n_zeros"]) / len(series)

    bins = config["plot"]["histogram"]["bins"].get(int)
    # Bins should never be larger than the number of distinct values
    bins = min(series_description["distinct_count_with_nan"], bins)
    stats["histogram_bins"] = bins

    bayesian_blocks_bins = config["plot"]["histogram"]["bayesian_blocks_bins"].get(bool)
    if bayesian_blocks_bins:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ret = bayesian_blocks(stats["histogramdata"])

            # Sanity check
            if not np.isnan(ret).any() and ret.size > 1:
                stats["histogram_bins_bayesian_blocks"] = ret

    return stats


def describe_date_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a date series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    stats = {"min": series.min(), "max": series.max(), "histogramdata": series}

    bins = config["plot"]["histogram"]["bins"].get(int)
    # Bins should never be larger than the number of distinct values
    bins = min(series_description["distinct_count_with_nan"], bins)
    stats["histogram_bins"] = bins

    stats["range"] = stats["max"] - stats["min"]

    return stats


def describe_categorical_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a categorical series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    # Make sure we deal with strings (Issue #100)
    series = series.astype(str)

    # Only run if at least 1 non-missing value
    value_counts = series_description["value_counts_without_nan"]

    stats = {"top": value_counts.index[0], "freq": value_counts.iloc[0]}

    check_composition = config["vars"]["cat"]["check_composition"].get(bool)
    if check_composition:
        contains = {
            "chars": series.str.contains(r"[a-zA-Z]", case=False, regex=True).any(),
            "digits": series.str.contains(r"[0-9]", case=False, regex=True).any(),
            "spaces": series.str.contains(r"\s", case=False, regex=True).any(),
            "non-words": series.str.contains(r"\W", case=False, regex=True).any(),
        }
        stats["max_length"] = series.str.len().max()
        stats["mean_length"] = series.str.len().mean()
        stats["min_length"] = series.str.len().min()
        stats["composition"] = contains

    stats["date_warning"] = warning_type_date(series)

    return stats


def describe_url_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a url series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    # Make sure we deal with strings (Issue #100)
    series = series[~series.isnull()].astype(str)

    stats = {}

    # Create separate columns for each URL part
    keys = ["scheme", "netloc", "path", "query", "fragment"]
    url_parts = dict(zip(keys, zip(*series.map(urlsplit))))
    for name, part in url_parts.items():
        stats["{}_counts".format(name.lower())] = pd.Series(
            part, name=name
        ).value_counts()

    # Only run if at least 1 non-missing value
    value_counts = series_description["value_counts_without_nan"]

    stats["top"] = value_counts.index[0]
    stats["freq"] = value_counts.iloc[0]

    return stats


def describe_path_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a path series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    # Make sure we deal with strings (Issue #100)
    series = series[~series.isnull()].astype(str)
    series = series.map(Path)

    common_prefix = os.path.commonprefix(list(series))
    if common_prefix == "":
        common_prefix = "No common prefix"

    stats = {"common_prefix": common_prefix}

    # Create separate columns for each path part
    keys = ["stem", "suffix", "name", "parent"]
    path_parts = dict(
        zip(keys, zip(*series.map(lambda x: [x.stem, x.suffix, x.name, x.parent])))
    )
    for name, part in path_parts.items():
        stats["{}_counts".format(name.lower())] = pd.Series(
            part, name=name
        ).value_counts()

    # Only run if at least 1 non-missing value
    value_counts = series_description["value_counts_without_nan"]

    stats["top"] = value_counts.index[0]
    stats["freq"] = value_counts.iloc[0]

    return stats


def describe_boolean_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a boolean series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    if config["compare_profile_analysis"].get(bool):
        value_counts1 = series_description["value_counts_without_nan1"]
        value_counts2 = series_description["value_counts_without_nan2"]

        stats = {"top1": value_counts1.index[0],
                 "top2": value_counts2.index[0],
                 "freq1": value_counts1.iloc[0],
                 "freq2": value_counts2.iloc[0]}

    value_counts = series_description["value_counts_without_nan"]

    stats = {"top": value_counts.index[0], "freq": value_counts.iloc[0]}

    return stats


def describe_constant_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a constant series (placeholder).

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        An empty dict.
    """
    return {}


def describe_unique_1d(series: pd.Series, series_description: dict) -> dict:
    """Describe a unique series (placeholder).

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        An empty dict.
    """
    if config["compare_profile_analysis"].get(bool):
        stats = {"date_warning1": warning_type_date(df1.loc[list0]),
                 "date_warning2": warning_type_date(df2.loc[list1])}
    stats = {"date_warning": warning_type_date(series)}

    return stats


def describe_supported(series: pd.Series, series_description: dict) -> dict:
    """Describe a supported series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """
    global list0, list1

    # number of observations in the Series
    leng = len(series)
    # TODO: fix infinite logic
    # number of non-NaN observations in the Series
    count = series.count()
    # number of infinite observations in the Series
    n_infinite = count - series.count()
    distinct_count = series_description["distinct_count_with_nan"]

    if config["compare_profile_analysis"].get(bool):
        series1 = series.loc[list0]
        series2 = series.loc[list1]
        leng1 = len(series1)
        leng2 = len(series2)
        # TODO: fix infinite logic
        # number of non-NaN observations in the Series
        count1 = series1.count()
        count2 = series2.count()
        # number of infinite observations in the Series
        n_infinite1 = count1 - series1.count()
        n_infinite2 = count2 - series2.count()
        # TODO: check if we prefer without nan
        distinct_count1 = series_description["distinct_count_with_nan1"]
        distinct_count2 = series_description["distinct_count_with_nan2"]

        stats = {
            "count": count,
            "distinct_count": distinct_count,
            "p_missing": 1 - count * 1.0 / leng,
            "n_missing": leng - count,
            "p_infinite": n_infinite * 1.0 / leng,
            "n_infinite": n_infinite,
            "is_unique": distinct_count == leng,
            "mode": series.mode().iloc[0] if count > distinct_count > 1 else series[0],
            "p_unique": distinct_count * 1.0 / leng,
            "memorysize": series.memory_usage(),
            "count1": count1,
            "distinct_count1": distinct_count1,
            "p_missing1": 1 - count1 * 1.0 / leng1,
            "n_missing1": leng1 - count1,
            "p_infinite1": n_infinite1 * 1.0 / leng1,
            "n_infinite1": n_infinite1,
            "is_unique1": distinct_count1 == leng1,
            "mode1": series1.mode().iloc[0] if count1 > distinct_count1 > 1 else series1[0],
            "p_unique1": distinct_count1 * 1.0 / leng1,
            "memorysize1": series1.memory_usage(),
            "count2": count2,
            "distinct_count2": distinct_count2,
            "p_missing2": 1 - count2 * 1.0 / leng2,
            "n_missing2": leng2 - count2,
            "p_infinite2": n_infinite2 * 1.0 / leng2,
            "n_infinite2": n_infinite2,
            "is_unique2": distinct_count2 == leng2,
            "mode2": series2.mode().iloc[0] if count2 > distinct_count2 > 1 else series2[0],
            "p_unique2": distinct_count2 * 1.0 / leng2,
            "memorysize2": series2.memory_usage(),
        }
    else:
        stats = {
            "count": count,
            "distinct_count": distinct_count,
            "p_missing": 1 - count * 1.0 / leng,
            "n_missing": leng - count,
            "p_infinite": n_infinite * 1.0 / leng,
            "n_infinite": n_infinite,
            "is_unique": distinct_count == leng,
            "mode": series.mode().iloc[0] if count > distinct_count > 1 else series[0],
            "p_unique": distinct_count * 1.0 / leng,
            "memorysize": series.memory_usage(),
        }

    return stats


def describe_unsupported(series: pd.Series, series_description: dict):
    """Describe an unsupported series.

    Args:
        series: The Series to describe.
        series_description: The dict containing the series description so far.

    Returns:
        A dict containing calculated series description values.
    """

    # number of observations in the Series
    leng = len(series)
    # number of non-NaN observations in the Series
    count = series.count()
    # number of infinte observations in the Series
    n_infinite = count - series.count()


    results_data = {
        "count": count,
        "p_missing": 1 - count * 1.0 / leng,
        "n_missing": leng - count,
        "p_infinite": n_infinite * 1.0 / leng,
        "n_infinite": n_infinite,
        "memorysize": series.memory_usage(),
    }

    return results_data


def describe_1d(series: pd.Series) -> dict:
    """Describe a series (infer the variable type, then calculate type-specific values).

    Args:
        series: The Series to describe.

    Returns:
        A Series containing calculated series description values.
    """

    # Replace infinite values with NaNs to avoid issues with histograms later.
    series.replace(to_replace=[np.inf, np.NINF, np.PINF], value=np.nan, inplace=True)

    # Infer variable types
    series_description = base.get_var_type(series)

    # Run type specific analysis
    if series_description["type"] == Variable.S_TYPE_UNSUPPORTED:
        series_description.update(describe_unsupported(series, series_description))
    else:
        series_description.update(describe_supported(series, series_description))

        type_to_func = {
            Variable.S_TYPE_CONST: describe_constant_1d,
            Variable.TYPE_BOOL: describe_boolean_1d,
            Variable.TYPE_NUM: describe_numeric_1d,
            Variable.TYPE_DATE: describe_date_1d,
            Variable.S_TYPE_UNIQUE: describe_unique_1d,
            Variable.TYPE_CAT: describe_categorical_1d,
            Variable.TYPE_URL: describe_url_1d,
            Variable.TYPE_PATH: describe_path_1d,
        }

        if series_description["type"] in type_to_func:
            series_description.update(
                type_to_func[series_description["type"]](series, series_description)
            )
        else:
            raise ValueError("Unexpected type")

    # Return the description obtained
    return series_description


def multiprocess_1d(column, series) -> Tuple[str, dict]:
    """Wrapper to process series in parallel.

    Args:
        column: The name of the column.
        series: The series values.

    Returns:
        A tuple with column and the series description.
    """
    return column, describe_1d(series)


def describe_table(df: pd.DataFrame, variable_stats: pd.DataFrame) -> dict:
    """General statistics for the DataFrame.

    Args:
      df: The DataFrame to describe.
      variable_stats: Previously calculated statistic on the DataFrame.

    Returns:
        A dictionary that contains the table statistics.
    """
    if config["compare_profile_analysis"].get(bool):
        df1 = df[df.index.isin(list0)]
        df2 = df[df.index.isin(list1)]
        n1 = len(df1)
        n2 = len(df2)
        # TODO: deep=True?
        memory_size1 = df1.memory_usage(index=True).sum()
        record_size1 = float(memory_size1) / n1
        memory_size2 = df2.memory_usage(index=True).sum()
        record_size2 = float(memory_size2) / n2

        table_stats = {
            "n1": n1,
            "n2": n2,
            "nvar": len(df.columns),
            "memsize1": memory_size1,
            "memsize2": memory_size2,
            "recordsize1": record_size1,
            "recordsize2": record_size2,
            "n_cells_missing1": variable_stats.loc["n_missing1"].sum(),
            "n_cells_missing2": variable_stats.loc["n_missing2"].sum(),
            "n_vars_with_missing1": sum((variable_stats.loc["n_missing1"] > 0).astype(int)),
            "n_vars_all_missing1": sum((variable_stats.loc["n_missing1"] == n1).astype(int)),
            "n_vars_with_missing2": sum((variable_stats.loc["n_missing2"] > 0).astype(int)),
            "n_vars_all_missing2": sum((variable_stats.loc["n_missing2"] == n2).astype(int)),
        }
        table_stats["p_cells_missing1"] = table_stats["n_cells_missing1"] / (
                table_stats["n1"] * table_stats["nvar"]
        )
        table_stats["p_cells_missing2"] = table_stats["n_cells_missing2"] / (
            table_stats["n2"] * table_stats["nvar"]
        )

        supported_columns = variable_stats.transpose()[
            variable_stats.transpose().type != Variable.S_TYPE_UNSUPPORTED
            ].index.tolist()
        table_stats["n_duplicates1"] = (
            sum(df1.duplicated(subset=supported_columns))
            if len(supported_columns) > 0
            else 0
        )
        table_stats["n_duplicates2"] = (
            sum(df2.duplicated(subset=supported_columns))
            if len(supported_columns) > 0
            else 0
        )
        table_stats["p_duplicates1"] = (
            (table_stats["n_duplicates1"] / len(df1))
            if (len(supported_columns) > 0 and len(df1) > 0)
            else 0
        )
        table_stats["p_duplicates2"] = (
            (table_stats["n_duplicates2"] / len(df2))
            if (len(supported_columns) > 0 and len(df2) > 0)
            else 0
        )

    n = len(df)
    # TODO: deep=True?
    memory_size = df.memory_usage(index=True).sum()
    record_size = float(memory_size) / n

    table_stats = {
        "n": n,
        "nvar": len(df.columns),
        "memsize": memory_size,
        "recordsize": record_size,
        "n_cells_missing": variable_stats.loc["n_missing"].sum(),
        "n_vars_with_missing": sum((variable_stats.loc["n_missing"] > 0).astype(int)),
        "n_vars_all_missing": sum((variable_stats.loc["n_missing"] == n).astype(int)),
    }

    table_stats["p_cells_missing"] = table_stats["n_cells_missing"] / (
        table_stats["n"] * table_stats["nvar"]
    )

    supported_columns = variable_stats.transpose()[
        variable_stats.transpose().type != Variable.S_TYPE_UNSUPPORTED
    ].index.tolist()
    table_stats["n_duplicates"] = (
        sum(df.duplicated(subset=supported_columns))
        if len(supported_columns) > 0
        else 0
    )
    table_stats["p_duplicates"] = (
        (table_stats["n_duplicates"] / len(df))
        if (len(supported_columns) > 0 and len(df) > 0)
        else 0
    )

    # Variable type counts
    table_stats.update({k.value: 0 for k in Variable})
    table_stats.update(
        dict(variable_stats.loc["type"].apply(lambda x: x.value).value_counts())
    )
    table_stats[Variable.S_TYPE_REJECTED.value] = (
        table_stats[Variable.S_TYPE_CONST.value]
        + table_stats[Variable.S_TYPE_CORR.value]
        + table_stats[Variable.S_TYPE_RECODED.value]
    )
    return table_stats


def warn_missing(missing_name, error):
    warnings.warn(
        "There was an attempt to generate the {missing_name} missing values diagrams, but this failed.\n"
        "To hide this warning, disable the calculation\n"
        '(using `df.profile_report(missing_diagrams={{"{missing_name}": False}}`)\n'
        "If this is problematic for your use case, please report this as an issue:\n"
        "https://github.com/pandas-profiling/pandas-profiling/issues\n"
        "(include the error message: '{error}')".format(
            missing_name=missing_name, error=error
        )
    )


def get_missing_diagrams(df: pd.DataFrame, table_stats: dict) -> dict:
    """Gets the rendered diagrams for missing values.

    Args:
        table_stats: The overall statistics for the DataFrame.
        df: The DataFrame on which to calculate the missing values.

    Returns:
        A dictionary containing the base64 encoded plots for each diagram that is active in the config (matrix, bar, heatmap, dendrogram).
    """
    missing_map = {
        "bar": {"func": plot.missing_bar, "min_missing": 0, "name": "Count"},
        "matrix": {"func": plot.missing_matrix, "min_missing": 0, "name": "Matrix"},
        "heatmap": {"func": plot.missing_heatmap, "min_missing": 2, "name": "Heatmap"},
        "dendrogram": {
            "func": plot.missing_dendrogram,
            "min_missing": 1,
            "name": "Dendrogram",
        },
    }

    missing = {}
    for name, settings in missing_map.items():
        if (
            config["missing_diagrams"][name].get(bool)
            and table_stats["n_vars_with_missing"] >= settings["min_missing"]
        ):
            try:
                if name != "heatmap" or (
                    table_stats["n_vars_with_missing"]
                    - table_stats["n_vars_all_missing"]
                    >= settings["min_missing"]
                ):
                    missing[name] = {
                        "name": settings["name"],
                        "matrix": settings["func"](df),
                    }
            except ValueError as e:
                warn_missing(name, e)
    return missing


def describe(df: pd.DataFrame) -> dict:
    """Calculate the statistics for each series in this DataFrame.

    Args:
        df: DataFrame.

    Returns:
        This function returns a dictionary containing:
            - table: overall statistics.
            - variables: descriptions per series.
            - correlations: correlation matrices.
            - missing: missing value diagrams.
            - messages: direct special attention to these patterns in your data.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be of type pandas.DataFrame")

    if df.empty:
        raise ValueError("df can not be empty")

    # Multiprocessing of Describe 1D for each column
    pool_size = config["pool_size"].get(int)
    if pool_size <= 0:
        pool_size = multiprocessing.cpu_count()

    if pool_size == 1:
        args = [(column, series) for column, series in df.iteritems()]
        series_description = {
            column: series
            for column, series in itertools.starmap(multiprocess_1d, args)
        }
    else:
        with multiprocessing.pool.ThreadPool(pool_size) as executor:
            series_description = {}
            results = executor.starmap(multiprocess_1d, df.iteritems())
            for col, description in results:
                series_description[col] = description

    # Mapping from column name to variable type
    variables = {
        column: description["type"]
        for column, description in series_description.items()
    }

    # Get correlations
    correlations = calculate_correlations(df, variables)

    # Check correlations between numerical variables
    if (
        config["check_correlation_pearson"].get(bool) is True
        and "pearson" in correlations
    ):
        # Overwrites the description with "CORR" series
        correlation_threshold = config["correlation_threshold_pearson"].get(float)
        update(
            series_description,
            perform_check_correlation(
                correlations["pearson"],
                lambda x: x > correlation_threshold,
                Variable.S_TYPE_CORR,
            ),
        )

    # Check correlations between categorical variables
    if (
        config["check_correlation_cramers"].get(bool) is True
        and "cramers" in correlations
    ):
        # Overwrites the description with "CORR" series
        correlation_threshold = config["correlation_threshold_cramers"].get(float)
        update(
            series_description,
            perform_check_correlation(
                correlations["cramers"],
                lambda x: x > correlation_threshold,
                Variable.S_TYPE_CORR,
            ),
        )

    # Check recoded
    if config["check_recoded"].get(bool) is True and "recoded" in correlations:
        # Overwrites the description with "RECORDED" series
        update(
            series_description,
            perform_check_correlation(
                correlations["recoded"], lambda x: x == 1, Variable.S_TYPE_RECODED
            ),
        )

    # Transform the series_description in a DataFrame
    variable_stats = pd.DataFrame(series_description)

    # Table statistics
    table_stats = describe_table(df, variable_stats)

    # missing diagrams
    missing = get_missing_diagrams(df, table_stats)

    # Messages
    messages = check_table_messages(table_stats)
    for col, description in series_description.items():
        messages += check_variable_messages(col, description)

    return {
        # Overall description
        "table": table_stats,
        # Per variable descriptions
        "variables": series_description,
        # Correlation matrices
        "correlations": correlations,
        # Missing values
        "missing": missing,
        # Warnings
        "messages": messages,
    }
