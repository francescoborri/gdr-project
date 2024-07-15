#! /usr/bin/env python3

import argparse
import sys
from datetime import timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from statsmodels.tsa.arima.model import ARIMA, ARIMAResults

from rrd import rrd_fetch
from utils import timedelta_type

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIMA forecast")
    parser.add_argument("filename", type=argparse.FileType("r"), help="Input RRD file")
    parser.add_argument(
        "-s",
        "--start",
        type=str,
        default="end-30d",
        metavar="START",
        help="start time from which fetch data (parsed by rrdtool using the AT-STYLE format), default is 30 days before the last observation in the file",
    )
    parser.add_argument(
        "-e",
        "--end",
        type=str,
        default="last",
        metavar="END",
        help="end time until which fetch data (parsed by rrdtool using the AT-STYLE format), default is the last observation in the file",
    )
    parser.add_argument(
        "-i",
        "--step",
        type=timedelta_type,
        default=None,
        metavar="STEP",
        help="preferred interval between 2 data points (note: if specified the data may be downsampled)",
    )
    parser.add_argument("-r", "--order", type=int, nargs=3, required=True, metavar=("p", "d", "q"), help="ARIMA order")
    parser.add_argument(
        "-R",
        "--seasonal_order",
        type=int,
        nargs=3,
        required="-m" in sys.argv or "--seasonal_period" in sys.argv,
        metavar=("P", "D", "Q"),
        help="seasonal ARIMA order (required if seasonal period is provided)",
    )
    parser.add_argument(
        "-m",
        "--seasonal_period",
        type=timedelta_type,
        required="-R" in sys.argv or "--seasonal_order" in sys.argv,
        metavar="SEAS_PERIOD",
        help="seasonal period (required if seasonal order is provided) (parsed by pandas.Timedelta, see https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.Timedelta.html for the available formats)",
    )
    parser.add_argument(
        "-f",
        "--forecast_period",
        type=timedelta_type,
        default=timedelta(days=1),
        metavar="FC_PERIOD",
        help="forecast period (parsed the same way as seasonal period), default is 1 day",
    )
    parser.add_argument(
        "-o",
        "--output_filename",
        type=argparse.FileType("w"),
        metavar="OUT",
        help="optional CSV output filename for the forecasted values",
    )

    args = parser.parse_args()
    start, end, step, data = rrd_fetch(filename=args.filename.name, start=args.start, end=args.end, step=args.step)

    season_offset = int(args.seasonal_period.total_seconds() // step.total_seconds()) if args.seasonal_period else 0

    if args.seasonal_period and season_offset < 2:
        parser.error(f"Seasonal period is too short since step is {step} and seasonal period is {args.seasonal_period}")
    elif args.seasonal_period.total_seconds() % step.total_seconds() != 0:
        parser.error("Seasonal period is not a multiple of the step")

    if args.output_filename:
        print("ds,timestamp,value", file=args.output_filename)

    for source in data:
        series = data[source].interpolate(method="time")

        fit: ARIMAResults = (
            ARIMA(series, order=args.order, seasonal_order=args.seasonal_order + [season_offset]).fit()
            if season_offset > 0
            else ARIMA(series, order=args.order).fit()
        )

        print(fit.summary())

        levels = [25, 50, 75]

        prediction_result = fit.get_prediction(start=start, end=end + args.forecast_period - step)
        prediction = prediction_result.predicted_mean
        prediction_conf_int = {
            level: prediction_result.conf_int(alpha=1 - level / 100) for level in levels
        }

        fig, ax = plt.subplots()
        ax.plot(series, color="black", label="Observed")
        ax.plot(prediction, color="blue", linestyle="--", label="Prediction")
        ax.axvline(x=end - step, color="black", linestyle=":", label="Last observation")

        for level, confidence_interval in prediction_conf_int.items():
            ax.fill_between(
                confidence_interval.index,
                confidence_interval["lower y"],
                confidence_interval["upper y"],
                color="orange",
                alpha=1 - level / 100,
                label=f"{level}% confidence interval",
                where=confidence_interval.index >= end,
            )

        ax.set_xlabel("Time")
        ax.set_ylabel(source)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.legend(loc="best")
        fig.autofmt_xdate()

        if args.output_filename:
            for dt, value in prediction.items():
                print(f"{source},{int(dt.timestamp())},{value}", file=args.output_filename)

    plt.show()
