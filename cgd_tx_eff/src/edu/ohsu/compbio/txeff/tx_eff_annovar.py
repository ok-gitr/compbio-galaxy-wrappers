'''
Read files generated by Annovar and write out a CSV file with variant transcript effects.

Input: One or more variant_function and exonic_variant_function files generated by Annovar. 

Output: CSV file

Created on Apr 14, 2022

@author: pleyte
'''

import argparse
import logging
from edu.ohsu.compbio.annovar import annovar_parser
from edu.ohsu.compbio.txeff.util.tx_eff_csv import TxEffCsv

VERSION = '0.0.1'

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
logging_format = '%(levelname)s: [%(filename)s:%(lineno)s - %(funcName)s()]: %(message)s'

stream_format = logging.Formatter(logging_format)
stream_handler.setFormatter(stream_format)
stream_handler.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)


def _parse_args():
    '''
    Validate and return command line arguments.
    '''
    parser = argparse.ArgumentParser(description='Read files generated by Annovar and write out a CSV file with variant transcript effects.')

    parser.add_argument('--annovar_variant_function', 
                        help='Annovar variant_function file',
                        type=argparse.FileType('r'),
                        required=True)

    parser.add_argument('--annovar_exonic_variant_function', 
                        help='Annovar exonic_variant_function file',
                        type=argparse.FileType('r'),
                        required=True)
    
    parser.add_argument('-o', '--out_file', 
                    help='Output CSV',
                    type=argparse.FileType('w'), 
                    required=True)

    parser.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    
    args = parser.parse_args()
        
    return args

def get_annovar_records(annovar_variant_function_filename: str, annovar_exonic_variant_function_filename: str):
    '''
    Parse Annovar records from the list files 
    '''
    if annovar_variant_function_filename == None or annovar_exonic_variant_function_filename is None:
        logger.warning(f"Annovar input file(s) not provided and this may cause errors during processing: vf={annovar_variant_function_filename}, evf={annovar_exonic_variant_function_filename}")
        
    annovar_records = list()
    annovarParser = annovar_parser.AnnovarParser()
    
    for file_name in [annovar_variant_function_filename, annovar_exonic_variant_function_filename]:
        file_transcripts = annovarParser.parse_file(file_name)
        logger.debug(f'Read {len(file_transcripts)} transcripts from {file_name}')    
        annovar_records.extend(file_transcripts)

    disinct_variant_count = len({f'{x.chromosome}-{x.position}-{x.reference}-{x.alt}' for x in annovar_records})
    logger.debug(f'Read {disinct_variant_count} distinct variants and {len(annovar_records)} transcripts from annovar files')

    # Merge like transcripts into a single annovar record 
    initial_size = len(annovar_records)
    annovar_records = annovarParser.merge(annovar_records)

    logger.info(f"Merged {initial_size} transcripts down to {len(annovar_records)}")
    return annovar_records

        
def _main():
    '''
    main function
    '''
    args = _parse_args()

    annovar_file_names = [x.name for x in args.annovar_file]
    annovar_records = get_annovar_records(annovar_file_names)

    logger.info(f"Writing {args.out_file.name}")    
    txEffCsv = TxEffCsv()
    txEffCsv.write_transcripts(args.out_file.name, annovar_records)

if __name__ == '__main__':
    _main()