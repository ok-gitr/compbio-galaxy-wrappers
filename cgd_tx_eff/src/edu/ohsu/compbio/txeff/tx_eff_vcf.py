'''
Created on Apr 29, 2022

@author: pleyte

Update a VCF with the variant-transcript details.  
'''
import argparse
import csv
from collections import defaultdict
import logging
import vcfpy
from edu.ohsu.compbio.txeff.variant import Variant
from edu.ohsu.compbio.txeff.variant_transcript import VariantTranscript

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
logging_format = '%(levelname)s: [%(filename)s:%(lineno)s - %(funcName)s()]: %(message)s'

stream_format = logging.Formatter(logging_format)
stream_handler.setFormatter(stream_format)
stream_handler.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)

VERSION = '0.0.1'

def _parse_args():
    '''
    Validate and return command line arguments.
    '''
    parser = argparse.ArgumentParser(description='Produce a VCF containing transcript details generated by tx_eff.hgvs.py')

    parser.add_argument('-i', '--in_vcf', 
                    help='Input VCF', 
                    type=argparse.FileType('r'), 
                    required=True)

    parser.add_argument('-o', '--out_vcf', 
                    help='Output VCF', 
                    type=argparse.FileType('w'), 
                    required=True)

    parser.add_argument('-c', '--in_csv', 
                    help='Input CSV', 
                    type=argparse.FileType('r'), 
                    required=True)
    
    parser.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    
    args = parser.parse_args()
    
    return args
    
    args = parser.parse_args()


def _read_vcf(vcf_filename: str):
    '''
    Read each variant from the VCF file and return a map of Variant[vcf-record]. Each variant must be unique and have only one ALT allele.  
    '''
    vcf_reader = vcfpy.Reader.from_path(vcf_filename)
    variant_dict = dict()
    
    for vcf_record in vcf_reader:
        if len(vcf_record.ALT) > 1:
            raise Exception(f'VCF variants must have just one ALT allel: {vcf_record.CHROM}-{vcf_record.POS}-{vcf_record.REF}-{vcf_record.ALT}')
        
        variant = Variant(vcf_record.CHROM, vcf_record.POS, vcf_record.REF, vcf_record.ALT[0].value)
        
        if variant_dict.get(variant):
            raise Exception(f"Duplicate variant in {vcf_filename}: {variant}")
        else:
            variant_dict[variant] = vcf_record
        
    vcf_reader.close()
    return variant_dict, vcf_reader.header


def _noneIfEmpty(value: str):
    '''
    Return None if the string is an empty string.
    ''' 
    if value == '':
        return None
    return value


def _read_hgvs_transcripts(csv_file_name):
    '''
    Read the transcripts that have been written to a CSV file by the ``tx_eff_hgvs.py`` script, and return a dictionary where 
    the key is a variant and the value is a list of transcripts 
    '''
    transcript_dict = defaultdict(list)
    
    with open(csv_file_name) as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            transcript = VariantTranscript(row['chromosome'], row['position'], row['reference'], row['alt'])
            transcript.variant_effect = row['variant_effect']
            transcript.variant_type = row['variant_type']
            transcript.hgvs_amino_acid_position = _noneIfEmpty(row['hgvs_amino_acid_position'])
            transcript.hgvs_base_position = _noneIfEmpty(row['hgvs_base_position'])
            transcript.exon = row['exon']
            transcript.hgnc_gene = row['hgnc_gene']
            transcript.hgvs_c_dot = row['hgvs_c_dot']
            transcript.hgvs_p_dot_one = row['hgvs_p_dot_one']
            transcript.hgvs_p_dot_three = row['hgvs_p_dot_three']
            transcript.splicing = row['splicing']
            transcript.refseq_transcript = row['refseq_transcript']
            transcript.protein_transcript = row['protein_transcript']
            
            variant = Variant(row['chromosome'], row['position'], row['reference'], row['alt'])
            
            transcript_dict[variant].append(transcript)
            
            logger.debug(f"{variant} has {len(transcript_dict[variant])} transcripts")
    
    return transcript_dict
    

def _add_transcripts_to_vcf(vcf_variant_dict, transcript_dict):
    '''
    Transform the transcript details into parallel arrays and add them to each VCF row.  
    '''
    vcf_records = list()
        
    for (variant, transcripts) in transcript_dict.items():
        vcf_record = vcf_variant_dict.get(variant)
        
        if not vcf_record:
            # raise Exception(f"VCF does not have {variant}")
            # jDebug: It is possible that annovar will change the genotype from what is in the VCF. I'll need to figure out how to deal with that.  Later... 
            logger.error(f"jDebug: Unable to find variant in VCF: {variant}")
            continue
        
        tfx_base_positions = list()
        tfx_exons = list()
        tfx_genes = list()
        tfx_c_dots = list()
        tfx_p1 = list()
        tfx_p3 = list()
        tfx_splice = list()
        tfx_refseq_transcripts = list()
        tfx_variant_effects = list()
        tfx_variant_types = list()
        tfx_protein_transcripts = list()
        
        for transcript in transcripts:
            tfx_base_positions.append(transcript.hgvs_base_position)
            tfx_exons.append(transcript.exon)
            tfx_genes.append(transcript.hgnc_gene)
            tfx_c_dots.append(transcript.hgvs_c_dot)
            tfx_p1.append(transcript.hgvs_p_dot_one)
            tfx_p3.append(transcript.hgvs_p_dot_three)
            tfx_splice.append(transcript.splicing)
            tfx_refseq_transcripts.append(transcript.refseq_transcript)
            tfx_variant_effects.append(transcript.variant_effect)
            tfx_variant_types.append(transcript.variant_type)
            tfx_protein_transcripts.append(transcript.protein_transcript)
            
        vcf_record.INFO['TFX_BASEP'] = [':'.join([str(x) for x in tfx_base_positions])]
        vcf_record.INFO['TFX_EXON'] = [':'.join([str(x) for x in tfx_exons])]
        vcf_record.INFO['TFX_HGNC'] = [':'.join([str(x) for x in tfx_genes])]
        vcf_record.INFO['TFX_HGVSC'] = [':'.join([str(x) for x in tfx_c_dots])]
        vcf_record.INFO['TFX_HGVSP1'] = [':'.join([str(x) for x in tfx_p1])]
        vcf_record.INFO['TFX_HGVSP3'] = [':'.join([str(x) for x in tfx_p3])]
        vcf_record.INFO['TFX_SPLICE'] = [':'.join([str(x) for x in tfx_splice])]
        
        # jDebug: Rename these three
        vcf_record.INFO['TFX_TXC'] = [':'.join([str(x) for x in tfx_refseq_transcripts])]
        vcf_record.INFO['TFX_VFX'] = [':'.join([str(x) for x in tfx_variant_effects])]
        vcf_record.INFO['TFX_PVT'] = [':'.join([str(x) for x in tfx_variant_types])]
        
        vcf_record.INFO['TFX_PROTEIN_TRANSCRIPT'] = [':'.join([str(x) for x in tfx_protein_transcripts])]
        
        vcf_records.append(vcf_record)
    
    return vcf_records


def _write_vcf(vcf_file_name, header: vcfpy.header.Header, vcf_records: list):
    '''
    Take the VCF records that have been updated with transcript effects and write them to file 
    '''
    writer = vcfpy.Writer.from_path(vcf_file_name, header)
    
    for vcf_record in vcf_records:
        writer.write_record(vcf_record)
        
    writer.close()


def _update_header(header):
    '''
    Add the new transcript effect fields to the VCF header 
    '''
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_BASEP'),
                                            ('Number', '.'),
                                            ('Type', 'String'),
                                            ('Description', 'Coding sequence start position.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_EXON'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Exon number associated with given '
                                                                            'transcript.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_HGNC'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'HGNC gene symbol.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_HGVSC'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'HGVS cdot nomenclature.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_HGVSP1'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'HGVS pdot nomenclature, single letter amino acids.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_HGVSP3'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'HGVS pdot nomenclature, three letter amino acids.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_SOURCE'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Annotation source.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_SPLICE'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Splice site annotation.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_TXC'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Transcript identifier.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_VFX'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Variant effect annotation.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_PVT'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Variant type or location annotation.')]))
    header.add_info_line(vcfpy.OrderedDict([('ID', 'TFX_PROTEIN_TRANSCRIPT'),
                                                            ('Number', '.'),
                                                            ('Type', 'String'),
                                                            ('Description', 'Protein transcript.')]))


def _main():
    '''
    main function
    '''
    args = _parse_args()
    
    vcf_variant_dict, vcf_header = _read_vcf(args.in_vcf.name)
    
    logger.info(f'Read {len(vcf_variant_dict)} variants from {args.in_vcf.name}')
    
    transcript_dict = _read_hgvs_transcripts(args.in_csv.name)
    
    logger.info(f'Read {len(transcript_dict)} distinct variants from {args.in_csv.name}')
    
    vcf_transcript_records = _add_transcripts_to_vcf(vcf_variant_dict, transcript_dict)
    
    # Add new INFO fields to VCF header
    _update_header(vcf_header) 
    
    logger.info(f"Writing VCF file {args.out_vcf.name}")
    _write_vcf(args.out_vcf.name, vcf_header, vcf_transcript_records)

if __name__ == '__main__':
    _main()