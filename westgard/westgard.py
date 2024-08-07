#!/usr/bin/env python

# DESCRIPTION: Extracts DSP counts data for specified TMA and Ab and plots Levey-Jennings chart. It will also execute
# Westgard multirule QC and reject samples that break the ruleset
# USAGE: python westgard.py <tma_results> <tma_combos>

# UPDATES:
# 1.0.0 -- added 5 TMA cell lines (total 19)
# 1.1.0 -- added default plots in the event that no rules are broken for a combination
# 1.2.0 -- removed stdout output file and added spreadsheet output of flagged batches
# 1.2.1 -- added function to plot positive controls for each TMA:Ab combo
# 1.2.2 -- updated pos_cntrl read-in to accept new file version

# By Benson Chong

import os
import numpy as np
import pandas as pd
import re
import matplotlib.pyplot as plt
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import argparse

VERSION = '1.2.2'

# initialize placeholder PDf object to be filled in
c = canvas.Canvas('placeholder.pdf', pagesize=letter)

def supply_args():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('dsp_tma_results', help='TMA melt of abundance counts from dsp_runner')
    parser.add_argument('pos_cntrls', help='Spreadsheet containing TMA:Ab combinations of positive controls')
    parser.add_argument('qc_report', help='PDF of plots')
    parser.add_argument('qc_tab', help='CSV sheet of QC report in tabular format')
    parser.add_argument('qc_pc_plots', help='PDF of positive controls plotted per cell line')
    parser.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    parser.add_argument('--combos', '-c')
    parser.add_argument('--tma', '-t')
    parser.add_argument('--ab', '-a')
    args = parser.parse_args()
    return args


# RegEx keyword search for TMA cell line name
def cellsearch(tma_input: str):
    cell_line_names = ['Tonsil', 'OvCar8+PARPi', 'BT474', 'MCF7', '468', 'Jurkat', 'Raji', 'THP1', 'PBMC+PHA',
                       '231', '453', 'Spleen', 'Liver', 'T47D', 'HeyA8', '436', 'abemaciclib', 'HCC1954',
                       'MCF10A+Gemcitabine']

    tma_oi = None

    for name in cell_line_names:
        if re.search(re.sub(r'[^\w]', '', tma_input), re.sub(r'[^\w]', '', name), re.IGNORECASE) or \
                re.search(re.sub(r'[^\w]', '', name), re.sub(r'[^\w]', '', tma_input), re.IGNORECASE):
            tma_oi = name
            break

    if tma_oi is None:
        raise NameError('Please enter valid TMA cell line name.')

    return tma_oi


# Plot positive controls faceted by TMA
def plot_pos_cntrls(sheet, abcount_path, pos_out):
    # initialize PDF
    pc = canvas.Canvas(pos_out, pagesize=letter)

    # Get positive controls from sheet
    sheet = pd.read_csv(sheet, sep='\t')

    tmas = sheet.iloc[:, 1].unique()
    pos_cntrls = {}

    for t in tmas:
        sub = sheet.loc[sheet.iloc[:, 1] == t]
        abs = []
        for i, r in sub.iterrows():
            abs.append(r[0])
        pos_cntrls[t] = abs

    # Iterate through TMA:Ab dict
    for k, v in pos_cntrls.items():
        df = pd.read_csv(abcount_path, header=0)

        # Select rows of specified TMA and Ab combination
        df = df[(df['name'] == k) & df['ProbeName'].isin(v)].reset_index()
        df = df[['name', 'ProbeName', 'abundance', 'year', 'monthday', 'batch']]
        df = df.sort_values(['year', 'monthday']).reset_index()

        # Get Counts
        for i in range(len(v)):
            counts = {}
            for j, row in df.iterrows():
                if row['ProbeName'] == v[i]:
                    counts[row['batch']] = row['abundance']
            # Check if abundance for TMA:Ab combos were found
            if len(counts) == 0:
                continue

            # Normalize
            y = get_counts(counts)
            y_zscore = []
            y_stat = get_stat(y)
            for ii in range(len(y)):
                y_zscore.append((y[ii]-y_stat[0])/y_stat[1])

            if i == 0:
                # PLOTTING
                x = np.arange(len(y))

                fig, ax = plt.subplots()
                plt.yticks([-3, -2, -1, 0, 1, 2, 3])
                ax.set_xticks(x)
                ax.set_yticklabels(['-3s', '-2s', '-1s', 'Mean', '1s', '2s', '3s'])
                ax.set_xticklabels(counts.keys())
                plt.xticks(fontsize=5, rotation=45, ha='right')

                plt.axhline(y=0, color='blue')
                plt.axhline(y=1, color='green', linestyle=':')
                plt.axhline(y=2, color='gold', linestyle='--')
                plt.axhline(y=3, color='red', linestyle='-')
                plt.axhline(y=-1, color='green', linestyle=':')
                plt.axhline(y=-2, color='gold', linestyle='--')
                plt.axhline(y=-3, color='red', linestyle='-')
                plt.title(k)

                figure = plt.gcf()
                figure.set_size_inches(8, 8)

                if len(x) != len(y):
                    continue
                else:
                    plt.plot(x, y_zscore, label=v[i])
                    plt.legend()
                    fig_name = str(i) + k
                    plt.savefig(fig_name + '.png', dpi=500)
                    pc.drawImage(fig_name + '.png', 30, 250, width=500, height=500)
                    os.remove(fig_name + '.png')
                    pc.showPage()
    pc.save()


# Extract count data from each initial batch dataset
def parse_batches(abcount_path, tma_oi, ab_oi):
    df = pd.read_csv(abcount_path, header=0)

    # Select rows of specified TMA and Ab combination
    df = df[(df['name'] == tma_oi) & (df['ProbeName'] == ab_oi)].reset_index()
    df = df[['name_ProbeName', 'abundance', 'year', 'monthday', 'batch']]
    df = df.sort_values(['year', 'monthday']).reset_index()

    counts = {}
    ids = {}

    for i, row in df.iterrows():
        id_name = f'Batch_{i + 1}_' + str(row['batch'])
        counts[row['batch']] = row['abundance']
        ids[id_name] = row['abundance']

    # Checks if Ab name is valid ProbeName
    if counts == {}:
        print(f'[ANTIBODY {ab_oi} WAS NOT FOUND IN DATASET.]\n')
        return

    return [counts, ids]


# Write out results in tabular format
def tab_out(abcount_path, tma_oi, ab_oi, flagged):
    counts = parse_batches(abcount_path, tma_oi, ab_oi)[0]
    y = get_counts(counts)
    stats = get_stat(y)
    df = pd.read_csv(abcount_path, header=0)

    # Select rows of specified TMA and Ab combination
    df = df[(df['name'] == tma_oi) & (df['ProbeName'] == ab_oi)].reset_index()
    df = df[['batch','name','ProbeName', 'abundance']]
    df['batch'] = df['batch'].astype(str)
    df['mean'] = [stats[0]] * df.shape[0]
    df['sd'] = [stats[1]] * df.shape[0]
    df['rules'] = [''] * df.shape[0]

    # Iterate through dictionary
    for k,v in flagged.items():
        if v:
            for batch in v:
                batch = batch.split('_')[-1]
                df.loc[df['batch'] == str(batch), 'rules'] = k

    df.replace('', np.nan, inplace=True)
    df.dropna(subset='rules', inplace=True)

    return df


# For getting annotations, e.g., 'Reference'
def get_key(my_dict, val):
    for k, v in my_dict.items():

        if val == v:
            return k
    return "Key doesn't exist"


# Obtain count values from dictionary
def get_counts(counts):
    y = []
    if not isinstance(counts, dict):
        raise TypeError('Please provide a dict')

    for k, v in counts.items():
        y.append(v)

    y = pd.Series(y)

    return y


def get_stat(y):
    mu, sigma = np.mean(y), np.std(y)
    pos_1s = mu + sigma
    pos_2s = mu + (2 * sigma)
    pos_3s = mu + (3 * sigma)
    neg_1s = mu + (-1 * sigma)
    neg_2s = mu + (-2 * sigma)
    neg_3s = mu + (-3 * sigma)
    return [mu, sigma, pos_1s, pos_2s, pos_3s, neg_1s, neg_2s, neg_3s]


def plot_lj_ax(y, counts):
    stats = get_stat(y)
    mu, pos_1s, pos_2s, pos_3s, neg_1s, neg_2s, neg_3s = stats[0], stats[2], stats[3], \
                                                         stats[4], stats[5], stats[6], stats[7]

    x_ticks = np.arange(len(y))

    fig, ax = plt.subplots()
    plt.yticks([neg_3s, neg_2s, neg_1s, mu, pos_1s, pos_2s, pos_3s])
    ax.set_xticks(x_ticks)
    ax.set_yticklabels(['-3s', '-2s', '-1s', 'Mean', '1s', '2s', '3s'])
    ax.set_xticklabels(counts.keys())
    plt.xticks(fontsize=5, rotation=45, ha='right')

    plt.axhline(y=mu, color='blue')
    plt.axhline(y=pos_1s, color='green', linestyle=':')
    plt.axhline(y=pos_2s, color='gold', linestyle='--')
    plt.axhline(y=pos_3s, color='red', linestyle='-')
    plt.axhline(y=neg_1s, color='green', linestyle=':')
    plt.axhline(y=neg_2s, color='gold', linestyle='--')
    plt.axhline(y=neg_3s, color='red', linestyle='-')

    figure = plt.gcf()
    figure.set_size_inches(8, 8)

    return figure


# Creates LJ chart
def chart(y, segment, title, f, rule_broke=True):
    x = np.arange(len(y))

    # Plots default LJ of counts
    if rule_broke is False:
        plt.gcf()
        fig_name = re.sub(r'[^\w]', '', title)
        plt.title(title)
        plt.plot(x, y, color='black', marker='o', markersize=3)
        plt.savefig(fig_name + '.png', dpi=500)
        c.drawImage(fig_name + '.png', 30, 250, width=500, height=500)
        os.remove(fig_name + '.png')
        c.showPage()

    # Plots counts with highlighted flagged batches
    else:
        plt.gcf()
        fig_name = re.sub(r'[^\w]', '', "_Rule:" + title).replace(" ", "")
        plt.title("Rule: " + title)
        plt.plot(x, y, color='blue', marker='o', markersize=3, linestyle='--')
        plt.plot(x[segment], y[segment], color='red', linewidth=3, marker='o', markersize=6)
        plt.savefig(fig_name + '.png', dpi=500)
        c.drawImage(fig_name + '.png', 30, 250, width=500, height=500)
        os.remove(fig_name + '.png')
        c.showPage()

    plt.close('all')


# multirule QC
def westgard_qc(counts: dict, ids: dict, tma_oi: str, ab_oi: str):
    x = get_counts(counts)
    stats = get_stat(x)
    mu, pos_1s, pos_2s, pos_3s, neg_1s, neg_2s, neg_3s = stats[0], stats[2], stats[3], stats[4], stats[5], stats[6], \
                                                         stats[7]

    # refine target name
    ab_oi = ab_oi.replace(r"/", "_")
    ab_oi = ab_oi.replace(" ", "")

    # Initialize ruleset dict with 0 values
    ruleset = {
        '1_3s': [],
        '2_2s': [],
        'R_4s': [],
        '2of3_2s': [],
        '3_1s': [],
        '6x': [],
        '7T': []
    }

    j = 1
    plotname = '_' + tma_oi + '_' + ab_oi

    for i in range(len(x)):
        f = plot_lj_ax(x, counts)

        # 1_3s rule
        if x[i] >= pos_3s or x[i] <= neg_3s:
            ruleset['1_3s'].append(list(ids.keys())[list(ids.values()).index(x[i])])
            chart(x, [i], '1_3s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
            j += 1

        # Rules spanning multiple data points
        if i > 0:

            # 2_2s rule
            if x[i - 1] > pos_2s and x[i] > pos_2s:
                ruleset['2_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 1])])
                chart(x, range((i - 1), (i + 1)),
                      '2_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif x[i - 1] < neg_2s and x[i] < neg_2s:
                ruleset['2_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 1])])
                chart(x, range((i - 1), (i + 1)),
                      '2_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            # R_4s rule
            if x[i - 1] >= pos_2s and x[i] <= neg_2s:
                ruleset['R_4s'].append(list(ids.keys())[list(ids.values()).index(x[i - 1])])
                chart(x, range((i - 1), (i + 1)),
                      'R_4s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif x[i] >= pos_2s and x[i - 1] <= neg_2s:
                ruleset['R_4s'].append(list(ids.keys())[list(ids.values()).index(x[i - 1])])
                chart(x, range((i - 1), (i + 1)),
                      'R_4s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

        # If rule spans 3+ data points
        if i >= 3:

            # 3_1s rule
            if x[i - 2] >= pos_1s and x[i - 1] >= pos_1s and x[i] >= pos_1s:
                ruleset['3_1s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '3_1s | ' + str(list(ids.keys())[list(ids.values()).index(x[i])]) + plotname, f)
                j += 1

            elif x[i - 2] <= neg_1s and x[i - 1] <= neg_1s and x[i] <= neg_1s:
                ruleset['3_1s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '3_1s | ' + str(list(ids.keys())[list(ids.values()).index(x[i])]) + plotname, f)
                j += 1

            # 2of3_2s rule
            if (x[i - 2] > mu and x[i - 1] > mu and x[i] > mu) and x[i - 2] > pos_2s and x[i - 1] > pos_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif (x[i - 2] > mu and x[i - 1] and x[i] > mu > mu) and x[i - 2] > pos_2s and x[i] > pos_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif (x[i - 2] > mu and x[i - 1] > mu and x[i] > mu) and x[i - 1] > pos_2s and x[i] > pos_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif (x[i - 2] > mu and x[i - 1] > mu and x[i] > mu) and x[i - 2] > pos_2s and x[i - 1] < neg_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif (x[i - 2] > mu and x[i - 1] > mu and x[i] > mu) and x[i - 2] > pos_2s and x[i] < neg_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

            elif (x[i - 2] > mu and x[i - 1] > mu and x[i] > mu) and x[i - 1] > pos_2s and x[i] < neg_2s:
                ruleset['2of3_2s'].append(list(ids.keys())[list(ids.values()).index(x[i - 2])])
                chart(x, range((i - 2), (i + 1)),
                      '2of3_2s | ' + list(ids.keys())[list(ids.values()).index(x[i])] + plotname, f)
                j += 1

        # If rule spans 6+ data points
        if i >= 6:

            # 6x rule
            if x[i - 5] > mu and x[i - 4] > mu and x[i - 3] > mu and x[i - 2] > mu and x[i - 1] > mu and x[i] > mu:
                ruleset['6x'].append(list(ids.keys())[list(ids.values()).index(x[i - 5])])
                chart(x, range((i - 5), (i + 1)),
                      '6x | ' + list(ids.keys())[list(ids.values()).index(x[i - 5])] + plotname, f)
                j += 1

            elif x[i - 5] < mu and x[i - 4] < mu and x[i - 3] < mu and x[i - 2] < mu and x[i - 1] < mu and x[i] < mu:
                ruleset['6x'].append(list(ids.keys())[list(ids.values()).index(x[i - 5])])
                chart(x, range((i - 5), (i + 1)),
                      '6x | ' + list(ids.keys())[list(ids.values()).index(x[i - 5])] + plotname, f)
                j += 1

        if i >= 7:

            # 7T rule -- alternative: if equal to or greater/less than
            if x[i - 6] < x[i - 5] < x[i - 4] < x[i - 3] < x[i - 2] < x[i - 1] < x[i]:
                ruleset['7T'].append(list(ids.keys())[list(ids.values()).index(x[i - 6])])
                chart(x, range((i - 6), (i + 1)),
                      '7T | ' + list(ids.keys())[list(ids.values()).index(x[i - 5])] + plotname, f)
                j += 1

            elif x[i - 6] > x[i - 5] > x[i - 4] > x[i - 3] > x[i - 2] > x[i - 1] > x[i]:
                ruleset['7T'].append(list(ids.keys())[list(ids.values()).index(x[i - 6])])
                chart(x, range((i - 6), (i + 1)),
                      '7T | ' + list(ids.keys())[list(ids.values()).index(x[i - 5])] + plotname, f)
                j += 1
        plt.close('all')

    rule_broke = False
    # Add dict of flagged batches to return
    flagged = {}

    for k, v in ruleset.items():
        if v:
            rule_broke = True
            print(f'Rule {k} is broken starting at batch(es): {v} for {tma_oi} | {ab_oi}\n')
            flagged[k] = v

    return [flagged, rule_broke]


def main():

    args = supply_args()

    # Error catching
    if args.combos is not None and args.ab is not None:
        raise Exception('A control sheet and --tma and/or --ab cannot be entered at once.')
    elif args.combos is not None and args.tma is not None:
        raise Exception('A control sheet and --tma and/or --ab cannot be entered at once.')
    elif args.combos is None and args.tma is not None and args.ab is None:
        raise Exception('Both TMA and Antibody name need to be provided.')
    elif args.combos is None and args.tma is None and args.ab is not None:
        raise Exception('Both TMA and Antibody name need to be provided')

    # Plots positive controls by default
    plot_pos_cntrls(args.pos_cntrls, args.dsp_tma_results, args.qc_pc_plots)
    plt.clf()

    if args.combos is None:
        batches = parse_batches(args.dsp_tma_results, args.tma, args.ab)
        counts, ids = batches[0], batches[1]
        westgard_out = westgard_qc(counts, ids, args.tma, args.ab)
        flagged, rule_broke = westgard_out[0], westgard_out[1]
        tab_df = tab_out(args.dsp_tma_results, args.tma, args.ab, flagged)

        if rule_broke is False:
            print(f'No rules broken for {args.tma}/{args.ab}\n')

        tab_df = tab_df.iloc[1:]
        tab_df.to_csv(args.qc_tab, index=False)
        c._filename = args.qc_report
        c.save()

    else:
        with open(args.combos) as f:
            columns = ['batch', 'name', 'ProbeName', 'abundance','mean', 'sd', 'rules']
            tab_df = pd.DataFrame([[0]*len(columns)], columns=columns)

            for combo in f:
                if combo.split(',')[0] == 'name':
                    continue

                tma_oi = combo.split(',')[0]
                ab_oi = combo.split(',')[1]
                batches = parse_batches(args.dsp_tma_results, tma_oi, ab_oi)
                if batches is None:
                    continue
                counts, ids = batches[0], batches[1]
                y = get_counts(counts)
                westgard_out = westgard_qc(counts, ids, tma_oi, ab_oi)
                flagged, rule_broke = westgard_out[0], westgard_out[1]
                tab_df = pd.concat([tab_df, tab_out(args.dsp_tma_results, tma_oi, ab_oi, flagged)])

                if rule_broke is False:
                    chart(y,0, f'TMA: {tma_oi} / Ab: {ab_oi}', plot_lj_ax(y, counts), False)
                    print(f'No rules broken for {tma_oi}/{ab_oi}\n')
                else:
                    continue

            # drop init zero row
            #tab_df = tab_df.iloc[1:]
            tab_df = tab_df.loc[~(tab_df == 0).all(axis=1)]

            # save files
            tab_df.to_csv(args.qc_tab, index=False)
            c._filename = args.qc_report
            c.save()


if __name__ == '__main__':
    main()