'''
Read file generated by tx_eff_annovar.py, update transcript information using HGVS, and write out a CSV file with variant transcript effects.

Requires Python 3.8. 
 - If you use Python 3.9 change the import of Iterable to ``from collections.abc import Iterable``
 
Created on Apr 20, 2022

@author: pleyte
'''

import argparse
import hgvs.assemblymapper
import hgvs.dataproviders.uta
import logging
import os
from collections import defaultdict
from edu.ohsu.compbio.txeff.variant_transcript import VariantTranscript
from edu.ohsu.compbio.txeff.variant import Variant
from hgvs.dataproviders.uta import UTABase
from hgvs.exceptions import HGVSInvalidVariantError, HGVSUsageError, HGVSDataNotAvailableError,\
    HGVSInvalidIntervalError, HGVSUnsupportedOperationError


# When we upgrade from python 3.8 to 3.9 this import needs to be changed to: "from collections.abc import Iterable"
from typing import Iterable
from edu.ohsu.compbio.annovar.annovar_parser import AnnovarVariantFunction
from edu.ohsu.compbio.txeff.util.tx_eff_csv import TxEffCsv

VERSION = '0.2.4'
ASSEMBLY_VERSION = "GRCh37"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
logging_format = '%(levelname)s: [%(filename)s:%(lineno)s - %(funcName)s()]: %(message)s'

stream_format = logging.Formatter(logging_format)
stream_handler.setFormatter(stream_format)
stream_handler.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)

# These will need to be updated when we switch from GRCh37 to GRCh38
CHROM_MAP = {'1': 'NC_000001.10', '2': 'NC_000002.11', '3': 'NC_000003.11', '4': 'NC_000004.11', '5': 'NC_000005.9',
             '6': 'NC_000006.11', '7': 'NC_000007.13', '8': 'NC_000008.10', '9': 'NC_000009.11', '10': 'NC_000010.10',
             '11': 'NC_000011.9', '12': 'NC_000012.11', '13': 'NC_000013.10', '14': 'NC_000014.8', '15': 'NC_000015.9',
             '16': 'NC_000016.9', '17': 'NC_000017.10', '18': 'NC_000018.9', '19': 'NC_000019.9', '20': 'NC_000020.10',
             '21': 'NC_000021.8', '22': 'NC_000022.10', 'X': 'NC_000023.10', 'Y': 'NC_000024.9', 'MT': 'NC_012920.1'}

def _noneIfEmpty(value: str):
    '''
    Return None if the string is an empty string.
    ''' 
    if value == '':
        return None
    return value

def _correct_indel_coords(pos, ref, alt):
    """
    Using a VCF position, create coords that are compatible with HGVS nomenclature.
    Since we are already determining at this stage whether the event is an ins or del, also
    include the ins or del strings in the result.
    substitution event -> ac:g.[pos][ref]>[alt]
    :return:
    """
    lref = len(ref)
    lalt = len(alt)
    if lref == 1 and lalt == 1:
        # Substitution case
        change = '>'.join([ref, alt])
        new_pos = str(pos) + change
        return new_pos
    elif lref == lalt:
        # Multi-nucleotide substitution case
        # NG_012232.1: g.12_13delinsTG
        new_start = str(pos)
        new_end = str(int(pos) + lref - 1)
        new_pos = '_'.join([new_start, new_end]) + 'delins' + alt
        return new_pos
    elif lref > lalt:
        # Deletion case
        shift = lref - lalt
        if shift == 1:
            new_pos = str(int(pos) + 1) + 'del'
            return new_pos
        else:
            new_start = str(int(pos) + 1)
            new_end = str(int(pos) + shift)
            new_pos = '_'.join([new_start, new_end]) + 'del'
            return new_pos
    elif lalt > lref:
        # Insertion case
        new_start = str(pos)
        new_end = str(int(pos) + 1)
        new_pos = '_'.join([new_start, new_end]) + 'ins' + alt[1:]
        return new_pos
    else:
        # OTHER case
        raise Exception(f"Change type not supported: {pos}:{ref}>{alt}")
        
def _lookup_hgvs_transcripts(variants: list):
    '''
    Return the HGVS transcripts associated with a list of variants  
    '''
    # Initialize the HGVS connection
    hdp = hgvs.dataproviders.uta.connect()
    am = hgvs.assemblymapper.AssemblyMapper(hdp, assembly_name=ASSEMBLY_VERSION, alt_aln_method='splign')
    hgvs_parser = hgvs.parser.Parser()
    
    transcripts = []
    for variant in variants:
        variant_transcripts = __lookup_hgvs_transcripts(hgvs_parser, hdp, am, variant)
        logger.info(f"HGVS found {len(variant_transcripts)} transcripts for {variant}")
        
        # HGVS might not find any transcripts even though Annovar did 
        if len(variant_transcripts) == 0:
            # jDebug: how do you know there are transcripts known to annovar? 
            logger.warning(f'HGVS could not find any transcripts for variant {variant} which has transcripts known to Annovar.')
        else:
            transcripts.extend(variant_transcripts)
    
    return transcripts

def __lookup_hgvs_transcripts(hgvs_parser: hgvs.parser.Parser, hdp: UTABase, am: hgvs.assemblymapper.AssemblyMapper, variant: Variant):
    '''
    Use HGVS/UTA to return a list of the transcripts for a variant
    '''
    logger.debug(f"Using HGVS/UTA to find transcripts for {variant}")
    
    hgvs_chrom = CHROM_MAP.get(variant.chromosome)
    
    if hgvs_chrom == None:
        logger.warning(f"Unknown chromosome: {variant.chromosome}-{variant.position}-{variant.reference}-{variant.alt}")
        return []
    
    # Look up the variant using HGVS            
    pos_part = _correct_indel_coords(variant.position, variant.reference, variant.alt)
    new_hgvs = hgvs_chrom + ':g.' + pos_part

    var_g = hgvs_parser.parse_hgvs_variant(new_hgvs)
    
    tx_list = hdp.get_tx_for_region(str(var_g.ac), 'splign', str(var_g.posedit.pos.start), str(var_g.posedit.pos.end))
    
    hgvs_transcripts = []
    
    for hgvs_transcript in tx_list:
        try:
            var_c = am.g_to_c(var_g, str(hgvs_transcript[0]))
            var_p = am.c_to_p(var_c)
            
            # Convert the three letter amino acid seq to a one letter and remove the transcript: prefix. 
            # Remove 'transcript:' to be left with only p.
            var_p1 = var_p.format(conf={"p_3_letter": False}).replace(var_p.ac+':','')
            var_p3 = var_p.format(conf={"p_3_letter": True}).replace(var_p.ac+':','')
            c_dot = var_c.type +'.' + str(var_c.posedit)

            variant_transcript = VariantTranscript(variant.chromosome, variant.position, variant.reference, variant.alt)
            variant_type = None
            
            # Annovar doesn't provide a gene for UTR and introns, so in those cases the gene information comes from HGVS using this function. 
            transcript_detail = hdp.get_tx_info(hgvs_transcript[0], hgvs_transcript[1], 'splign')
            variant_transcript.hgnc_gene = transcript_detail['hgnc'] 
            
            # The amino acid position only exists for certain types of variants.             
            if var_p3 == 'p.?':
                assert var_p.posedit == None, "A position is not expected with 'p.?'"                
            elif isinstance(var_p.posedit, hgvs.edit.AARefAlt):
                # Some variants don't have any position information, and that is ok. Most of the time these are indels, as indicated by ``var_p.posedit.type``
                logger.debug(f"HGVS variant does not have a position: ref={var_p.posedit.ref}, alt={var_p.posedit.alt}, type={var_p.posedit.type}, str={str(var_p.posedit)}. Keeping.")
            else:
                variant_transcript.hgvs_amino_acid_position = var_p.posedit.pos.start.pos
            
            variant_transcript.hgvs_base_position = var_c.posedit.pos.start.base
            variant_transcript.hgvs_c_dot = c_dot
            variant_transcript.hgvs_p_dot_one = var_p1
            variant_transcript.hgvs_p_dot_three = var_p3
            variant_transcript.refseq_transcript = var_c.ac
            variant_transcript.variant_type = variant_type
            variant_transcript.protein_transcript = var_p.ac
            
            hgvs_transcripts.append(variant_transcript)
        
        except HGVSUsageError as e:
            if("non-coding transcript" in e.args[0]):
                logger.info(f"Error caused by non-coding transcript, skipping {variant}: %s", str(e))
            else:
                raise(e)
        except HGVSInvalidVariantError as e:            
            logger.warning(f"Invalid variant {variant}: %s", str(e))
            raise(e)
        except HGVSUnsupportedOperationError as e:
            logger.warning(f"Invalid parameters while processing variant={variant}, var_g={var_g}, transcript={str(hgvs_transcript[0])}: %s", str(e))
        except HGVSInvalidIntervalError as e:
            logger.warning(f"Invalid variant interval {variant}: %s", str(e))
        except HGVSDataNotAvailableError as e:
            logger.warn(f"Unable to use HGVS to parse variant {variant}: %s", str(e))
    
    return hgvs_transcripts


def _get_unmatched_annovar_transcripts(annovar_dict: defaultdict(list), hgvs_dict: defaultdict(list)):
    '''
    After HGVS and Annovar transcripts have been merged, this function can be called to find Annovar transcripts that were not paired 
    with an HGVS trancsript. 
    '''
    transcripts = []
    
    for (transcript_key, annovar_transcript_list) in annovar_dict.items():
        # Check the HGVS dictionary for a key matching the annovar key. If there is a match, then the annovar transcript has already  
        # been processed. If HGVS does not have the key then the annovar transcript has not been looked at.
        if hgvs_dict.get(transcript_key) == None:
            logger.debug(f"Adding unmatched Annovar transcript(s) for {transcript_key}")
            
            # Convert the AnnovarVariantFunction objects to VariantTranscript so all items in the list are of the same type. 
            for annovar_transcript in annovar_transcript_list:
                transcripts.append(to_variant_transcript(annovar_transcript))
    
    for (transcript_key, hgvs_transcript_list) in hgvs_dict.items():
        if annovar_dict.get(transcript_key) == None:
            logger.debug(f"Adding unmatched HGVS transcript(s) for {transcript_key}")
            transcripts.extend(hgvs_transcript_list)
    
    return transcripts

def to_variant_transcript(annovar_transcript: AnnovarVariantFunction):
        '''
        Create a new VariantTranscript using the values from an object of parent type AnnovarVariantFunction
        '''
        variant_transcript = VariantTranscript(annovar_transcript.chromosome, annovar_transcript.position, annovar_transcript.reference, annovar_transcript.alt)
        variant_transcript.protein_transcript = None
        variant_transcript.variant_effect = annovar_transcript.variant_effect
        variant_transcript.variant_type = annovar_transcript.variant_type
        variant_transcript.hgvs_amino_acid_position = annovar_transcript.hgvs_amino_acid_position
        variant_transcript.hgvs_base_position = annovar_transcript.hgvs_base_position
        variant_transcript.exon = annovar_transcript.exon
        variant_transcript.hgnc_gene = annovar_transcript.hgnc_gene
        variant_transcript.hgvs_c_dot = annovar_transcript.hgvs_c_dot
        variant_transcript.hgvs_p_dot_one = annovar_transcript.hgvs_p_dot_one
        variant_transcript.hgvs_p_dot_three = annovar_transcript.hgvs_p_dot_three
        variant_transcript.splicing = annovar_transcript.splicing
        variant_transcript.refseq_transcript = annovar_transcript.refseq_transcript
        return variant_transcript
        
def _merge_annovar_with_hgvs(annovar_transcripts: list, hgvs_transcripts: list, require_match=True):
    '''
    Given a list of transcripts from Annovar and HGVS, find those with the same genotype and transcript, and merge them into a single record.
    
    The optional ``require_match`` parameter can be used to indicate that only transcripts which are found in both the Annovar 
    and HGVS lists, are returned.       
    '''
    transcripts = []
    
    # Collect annovar records into a map keyed by genotype and transcript 
    annovar_dict = defaultdict(list)
    key_maker = lambda x: "-".join([x.chromosome, str(x.position), x.reference, x.alt, x.refseq_transcript])
    for annovar_rec in annovar_transcripts:
        annovar_dict[key_maker(annovar_rec)].append(annovar_rec)
    
    # Collect hgvs records into a map keyed by genotype and transcript    
    hgvs_dict = defaultdict(list)
    for hgvs_rec in hgvs_transcripts:
        hgvs_dict[key_maker(hgvs_rec)].append(hgvs_rec)

    # Iterate over every HGVS variant-transcript and see if there is a matching Annovar transcript
    for (transcript_key, hgvs_transcript_list) in hgvs_dict.items():
        # The dictionary stores the HGVS transcript in a list, but there will only be one HGVS transcript in the list. 
        assert len(hgvs_transcript_list) == 1
        hgvs_transcript = hgvs_transcript_list[0]
        
        annovar_matches = annovar_dict.get(transcript_key)
        if not annovar_matches:
            logger.debug(f"HGVS {transcript_key} does not match any Annovar transcripts")
        else:
            logger.debug(f"Merging HGVS transcript with {len(annovar_matches)} Annovar transcripts having key {transcript_key}")
            transcripts.append(_merge(transcript_key, hgvs_transcript, annovar_matches))

    # If matching is not required, then add unmatched Annovar transcripts to the final list
    if require_match == False:
        transcripts.extend(_get_unmatched_annovar_transcripts(annovar_dict, hgvs_dict))

    return transcripts

def _merge(transcript_key: str, hgvs_transcript: VariantTranscript, annovar_transcripts: Iterable[VariantTranscript]):
    '''
    Combine Annovar and HGVS information relating to the same transcript into a single record.  
    '''
    new_transcript = VariantTranscript(hgvs_transcript.chromosome, hgvs_transcript.position, hgvs_transcript.reference, hgvs_transcript.alt)

    for annovar_transcript in annovar_transcripts:
        _merge_into(transcript_key, new_transcript, hgvs_transcript, annovar_transcript)
        
    return new_transcript


def _merge_into(transcript_key: str, new_transcript: VariantTranscript, hgvs_transcript: VariantTranscript, annovar_transcript: VariantTranscript):
    '''
    Take the best parts of the hgvs_transcript and the annovar_transcript, and place them in the new_transcript 
    '''
    assert hgvs_transcript.chromosome == annovar_transcript.chromosome, f"HGVS and Annovar genotype chromosomes are not equal: {hgvs_transcript.chromosome} != {annovar_transcript.chromosome}"
    assert hgvs_transcript.position == annovar_transcript.position, f"HGVS and Annovar genotype positions are not equal: {hgvs_transcript.position} != {annovar_transcript.position}"
    assert hgvs_transcript.reference == annovar_transcript.reference, f"HGVS and Annovar genotype references are not equal: {hgvs_transcript.reference} != {annovar_transcript.reference}"
    assert hgvs_transcript.alt == annovar_transcript.alt, f"HGVS and Annovar genotype alts are not equal: {hgvs_transcript.alt} != {annovar_transcript.alt}"
    
    # Amino Acid Position
    ## Amino acid position is commonly different between HGVS and Annovar 
    if str(hgvs_transcript.hgvs_amino_acid_position) != str(annovar_transcript.hgvs_amino_acid_position):
        logger.debug(f"HGVS and Annovar do not agree on amino acid position for {transcript_key}: {hgvs_transcript.hgvs_amino_acid_position} != {annovar_transcript.hgvs_amino_acid_position}")

    if _allow_merge(new_transcript.hgvs_amino_acid_position, hgvs_transcript.hgvs_amino_acid_position, transcript_key, 'hgvs_amino_acid_position'):
        new_transcript.hgvs_amino_acid_position = hgvs_transcript.hgvs_amino_acid_position 
    
    # Base Position
    ## Base position may not match what HGVS says; can be empty; or will match between annovar and hgvs    
    if str(hgvs_transcript.hgvs_base_position) != str(annovar_transcript.hgvs_base_position):
        logger.debug(f"HGVS and Annovar do not agree on base_position for {transcript_key}: {hgvs_transcript.hgvs_base_position} != {annovar_transcript.hgvs_base_position}")    
    
    if _allow_merge(new_transcript.hgvs_base_position, hgvs_transcript.hgvs_base_position, transcript_key, 'hgvs_base_position'):
        new_transcript.hgvs_base_position = hgvs_transcript.hgvs_base_position
    
    # Exon number
    ## Only Annovar provides exon, and the value may be empty.
    assert hgvs_transcript.exon == None
    if _allow_merge(new_transcript.exon, annovar_transcript.exon, transcript_key, 'exon'):
        new_transcript.exon = annovar_transcript.exon 
    
    # Gene
    # Prefer annovar's gene, but annovar doesn't give us a gene for intron and utr; in those cases use hgvs's.        
    transcript_gene = annovar_transcript.hgnc_gene
    if _noneIfEmpty(annovar_transcript.hgnc_gene) == None and _noneIfEmpty(hgvs_transcript.hgnc_gene) == None:
        logger.debug(f"Gene selection: Neither Annovar or HGVS have a gene for {transcript_key}") 
    elif annovar_transcript.hgnc_gene == None:
        logger.debug(f"Gene selection: Annovar did not provide a gene for {transcript_key}, using HGVS's: gene={hgvs_transcript.hgnc_gene}")            
        transcript_gene = hgvs_transcript.hgnc_gene
    elif annovar_transcript.hgnc_gene != hgvs_transcript.hgnc_gene:
        logger.debug(f"Gene selection: Annovar and HGVS genes don't match for {transcript_key}: {annovar_transcript.hgnc_gene} != {hgvs_transcript.hgnc_gene}")
    
    if _allow_merge(new_transcript.hgnc_gene, transcript_gene, transcript_key, 'hgnc_gene'):
        new_transcript.hgnc_gene = transcript_gene
    
    # c-dot
    ## Use HGVS's c. because Annovar's is not always correct
    assert hgvs_transcript.hgvs_c_dot != None, "The HGVS c. value is not supposed to be empty"
    
    if hgvs_transcript.hgvs_c_dot != annovar_transcript.hgvs_c_dot:
        logger.debug(f"HGVS and Annovar do not agree on c_dot for {transcript_key}: {hgvs_transcript.hgvs_c_dot} != {annovar_transcript.hgvs_c_dot} ")

    if _allow_merge(new_transcript.hgvs_c_dot, hgvs_transcript.hgvs_c_dot, transcript_key, 'hgvs_c_dot'):
        new_transcript.hgvs_c_dot = hgvs_transcript.hgvs_c_dot
    
    # p-dot (1L)
    ## Use HGVS's p. because Annovar's is not always correct 
    assert hgvs_transcript.hgvs_p_dot_one != None
    
    if hgvs_transcript.hgvs_p_dot_one != annovar_transcript.hgvs_p_dot_one:
        logger.debug(f"HGVS and Annovar do not agree on hgvs_p_dot_one for {transcript_key}: {hgvs_transcript.hgvs_p_dot_one} != {annovar_transcript.hgvs_p_dot_one} ")

    if _allow_merge(new_transcript.hgvs_p_dot_one, hgvs_transcript.hgvs_p_dot_one, transcript_key, 'hgvs_p_dot_one'):
        new_transcript.hgvs_p_dot_one = hgvs_transcript.hgvs_p_dot_one
    
    # p-dot (3L)
    assert hgvs_transcript.hgvs_p_dot_three != None

    if hgvs_transcript.hgvs_p_dot_three != annovar_transcript.hgvs_p_dot_three:
        logger.debug(f"HGVS and Annovar do not agree on hgvs_p_dot_three for {transcript_key}: {hgvs_transcript.hgvs_p_dot_three} != {annovar_transcript.hgvs_p_dot_three} ")

    if _allow_merge(new_transcript.hgvs_p_dot_three, hgvs_transcript.hgvs_p_dot_three, transcript_key, 'hgvs_p_dot_three'):
        new_transcript.hgvs_p_dot_three = hgvs_transcript.hgvs_p_dot_three
    
    # Splice variant indicator
    ## HGVS never tells us that a variant/transcript is involved in splicing. But Annovar does. 
    assert hgvs_transcript.splicing == None
    if _allow_merge(new_transcript.splicing, annovar_transcript.splicing, transcript_key, 'splicing'):
        new_transcript.splicing = annovar_transcript.splicing

    # Refseq Transcript
    assert hgvs_transcript.refseq_transcript == annovar_transcript.refseq_transcript
    if _allow_merge(new_transcript.refseq_transcript, annovar_transcript.refseq_transcript, transcript_key, 'refseq_transcript'):
        new_transcript.refseq_transcript = annovar_transcript.refseq_transcript
        
    # Variant Effect 
    ## variant effect is only provided by Annovar, and the value may be empty
    assert hgvs_transcript.variant_effect == None
    if _allow_merge(new_transcript.variant_effect, annovar_transcript.variant_effect, transcript_key, 'variant_effect'):
        new_transcript.variant_effect = annovar_transcript.variant_effect
    
    # Variant Type 
    ## Variant type is only provided by Annovar, and the value will be empty in the case of splice variants. 
    assert hgvs_transcript.variant_type == None
    if annovar_transcript.splicing != 'splicing':
        assert _noneIfEmpty(annovar_transcript.variant_type) != None, f'Variant type must not be empty for non-splicing transcripts. See {transcript_key}'

    if _allow_merge(new_transcript.variant_type, annovar_transcript.variant_type, transcript_key, 'variant_type'):
        new_transcript.variant_type = annovar_transcript.variant_type 
     
    # Protein Transcript
    ## Only HGVS provides protein transcript
    assert hgvs_transcript.protein_transcript != None
    if _allow_merge(new_transcript.protein_transcript, hgvs_transcript.protein_transcript, transcript_key, 'protein_transcript'):
        new_transcript.protein_transcript = hgvs_transcript.protein_transcript
    
    return new_transcript
    

def _allow_merge(existing_value, new_value, variant_id, field_name):
    '''
    The merge functions in this script combine values from the HGVS UTA database with one, and sometimes two Annovar records. Once a value is 
    added to the new "merged" record, we don't want to overwrite that value with a different value. This step is just to make sure that 
    out assumptions about incoming data are correct.    
    '''
    if existing_value and new_value and existing_value != new_value:
        # The existing value has already been set and the incoming value is non-empty, and the two values are different
        raise Exception(f"Unexpected merge condition for {variant_id}: existing {field_name} value does not match new value: {existing_value} != {new_value}")
    elif existing_value != None and not new_value:
        # Don't overwrite a valid value with an empty value
        return False
    else:
        return True


def get_summary(require_match: bool, annovar_transcripts: list, annovar_variants: set, hgvs_transcripts: list, merged_transcripts: list):
    '''
    Return a collection of summary statistics after processing completes. 
    '''
    results = dict()
    results['arg_require_match'] = require_match
    results['annovar_transcript_count'] = len(annovar_transcripts)
    results['annovar_distinct_variant_count'] = len(annovar_variants)
    results['hgvs_transcript_count'] = len(hgvs_transcripts)
    
    results['hgvs_distinct_variant_count'] = len(set(map(lambda x: Variant(x.chromosome, x.position, x.reference, x.alt), hgvs_transcripts)))
    
    # Collect annovar records into a map keyed by genotype and transcript
    key_maker = lambda x: "-".join([x.chromosome, str(x.position), x.reference, x.alt, x.refseq_transcript])
    annovar_dict = defaultdict(list)
     
    annovar_splice_variant_transcript_count = 0
    
    # Collect annovar records into a map keyed by genotype and transcript
    for annovar_rec in annovar_transcripts:
        if annovar_rec.splicing == 'splicing' or annovar_rec.splicing == 'ncRNA_splicing':
            annovar_splice_variant_transcript_count += 1
        elif annovar_rec.splicing != None and annovar_rec.splicing != '':
            logger.warning(f"Invalid value in splicing column: {annovar_rec.splicing}")

        annovar_dict[key_maker(annovar_rec)].append(annovar_rec)
    
    results['annovar_splice_variant_transcript_count'] = annovar_splice_variant_transcript_count
    
    # Collect hgvs records into a map keyed by genotype and transcript    
    hgvs_dict = defaultdict(list)
    for hgvs_rec in hgvs_transcripts:
        hgvs_dict[key_maker(hgvs_rec)].append(hgvs_rec)
    
    # Collect merged hgvs and annovar recoreds into a map keyed by genotype and transcript
    merged_dict = defaultdict(list)
    for merged_rec in merged_transcripts:
        merged_dict[key_maker(merged_rec)].append(merged_rec)
    
    matched_annovar_and_hgvs_transcript_count = 0
    unmatched_annovar_transcript_count = 0
    unmatched_hgvs_transcript_count = 0

    all_transcript_keys = set()
    all_transcript_keys.update(annovar_dict.keys())
    all_transcript_keys.update(hgvs_dict.keys())
     
    for transcript_key in all_transcript_keys:
        if annovar_dict.get(transcript_key) and hgvs_dict.get(transcript_key):
            assert merged_dict.get(transcript_key)
            matched_annovar_and_hgvs_transcript_count += 1
        elif annovar_dict.get(transcript_key) and not hgvs_dict.get(transcript_key):
            unmatched_annovar_transcript_count += 1
        elif hgvs_dict.get(transcript_key) and not annovar_dict.get(transcript_key):
            unmatched_hgvs_transcript_count += 1
        else:
            raise Exception("Unexpected summary condition")
    
    results['matched_annovar_and_hgvs_transcript_count'] = matched_annovar_and_hgvs_transcript_count
    results['unmatched_annovar_transcript_count'] = unmatched_annovar_transcript_count
    results['unmatched_hgvs_transcript_count'] = unmatched_hgvs_transcript_count    
    results['merged_transcript_count'] = len(merged_transcripts)
    
    
    merged_distinct_variant_count = len(set(map(lambda x: Variant(x.chromosome, x.position, x.reference, x.alt), merged_transcripts)))
    results['merged_distinct_variant_count'] = merged_distinct_variant_count 
    
    # Sanity check: The number of HGVS transcripts minus the count of merged HGVS transcripts is equal to the number of merged HGVS and annovar transcripts.    
    sanity_check_hgvs = (len(hgvs_transcripts) - unmatched_hgvs_transcript_count) == matched_annovar_and_hgvs_transcript_count
    if not sanity_check_hgvs:
        logger.debug(f"Failed sanity check 'sanity_check_hgvs': {len(hgvs_transcripts)} - {unmatched_hgvs_transcript_count} != {matched_annovar_and_hgvs_transcript_count}")
    
    # Sanity check: The number of annovar transcripts minus the count of merged annovar transcripts, minus the number of 
    # splice variants is equal to the number of merged HGVS and annovar transcripts. Splice variants must be subtradcted because 
    # they get counted twice - once as a splice variant and once as an exonic or intronic variant. 
    sanity_check_annovar = (len(annovar_transcripts) - unmatched_annovar_transcript_count - annovar_splice_variant_transcript_count) == matched_annovar_and_hgvs_transcript_count    
    # sanity_check_annovar = (len(annovar_transcripts) - unmatched_annovar_transcript_count) == matched_annovar_and_hgvs_transcript_count
    if not sanity_check_annovar:
        logger.debug(f"Failed sanity check 'sanity_check_annovar': {len(annovar_transcripts)} - {unmatched_annovar_transcript_count} - {annovar_splice_variant_transcript_count} != {matched_annovar_and_hgvs_transcript_count}")

    # Essential sanity check:  
    # Sanity check is currently off by just a little bit. 
    if not sanity_check_hgvs or not sanity_check_annovar:
        logger.info(f'Failed sanity check: Total number of transcripts does not equal sum of matched, and unmatched ({sanity_check_hgvs} and {sanity_check_annovar}).')
         
    # Non-essential sanity check: all variants from annovar have at least one transcript in the final output
    sanity_check_variant_coverage = merged_distinct_variant_count == results['annovar_distinct_variant_count']
    if not sanity_check_variant_coverage:
        logger.warning(f"Not all of the Annovar variants made it into the list of variant-transcripts ({merged_distinct_variant_count}/{results['annovar_distinct_variant_count']})")

    sanity_check = sanity_check_hgvs and sanity_check_annovar and sanity_check_variant_coverage
    results['sanity_check'] = sanity_check

    return results


def _log_summary(results: dict):
    '''
    Display summary of updated transcripts
    ''' 
    
    logger.info(f"Argument require_match: {results['arg_require_match']}")
    logger.info(f"Number of annovar transcripts: {results['annovar_transcript_count']}")
    logger.info(f"Number of Annovar transcripts that are splice variants: {results['annovar_splice_variant_transcript_count']}")
    logger.info(f"Number of distinct variants from Annovar: {results['annovar_distinct_variant_count']}")    
    logger.info(f"Number of HGVS transcripts: {results['hgvs_transcript_count']}")
    logger.info(f"Number of distinct variants from HGVS: {results['hgvs_distinct_variant_count']}")
    logger.info(f"Number of transcripts matched in Annovar and HGVS: {results['matched_annovar_and_hgvs_transcript_count']}")
    logger.info(f"Number of Annovar transcripts not matched with HGVS transcripts: {results['unmatched_annovar_transcript_count']}")
    logger.info(f"Number of HGVS transcripts not matched with Annovar transcripts: {results['unmatched_hgvs_transcript_count']}")
    logger.info(f"Number of distinct variants in merged transcript list: {results['merged_distinct_variant_count']}")
    logger.info(f"Total number of transcripts in final list: {results['merged_transcript_count']}")
    logger.info(f"Sanity check: {'Passed' if results['sanity_check'] else 'Failed' }")

def _parse_args():
    '''
    Validate and return command line arguments.
    '''
    parser = argparse.ArgumentParser(description='Read file generated by tx_eff_annovar.py, update transcript information using HGVS, and write out a CSV file with variant transcript effects.')

    parser.add_argument('-i', '--in_file',  
                        help='Input CSV (generated by tx_eff_annovar.py)',
                        type=argparse.FileType('r'),
                        required=True)
        
    parser.add_argument('-o', '--out_file', 
                        help='Output CSV', 
                        type=argparse.FileType('w'), 
                        required=True)
    
    parser.add_argument('-r', '--require_match',
                        help='Keep only transcripts that are found in both HGVS and Annovar',
                        action='store_true')
    
    parser.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    
    args = parser.parse_args()
        
    # Log the location of HGVS' datasources
    identify_hgvs_datasources()    

    return args


def identify_hgvs_datasources():
    '''
    Check the environment for definitions of HGVS' datasources and log the findings 
    '''
    if os.environ.get('HGVS_SEQREPO_DIR') == None:
        logger.warning("The HGVS_SEQREPO_DIR environment variable is not defined. The remote seqrepo database will be used.")
    else:
        logger.info(f"Using SeqRepo {os.environ.get('HGVS_SEQREPO_DIR')}")
    
    if os.environ.get('UTA_DB_URL') == None:
        logger.warning("The UTA_DB_URL environment variable is not defined. The remote UTA database will be used.")
    else:
        logger.info(f"Using UTA Database at {os.environ.get('UTA_DB_URL')}")

def get_updated_hgvs_transcritpts(annovar_transcripts: list, require_match: bool):    
    '''
    Take a list of transcripts from Annovar and use them to look up the corresponding variants using the HGVS python lib; and then 
    merge the annovar and hgvs info and return the results. 
    '''
    disinct_variants = {Variant(x.chromosome, x.position, x.reference, x.alt) for x in annovar_transcripts}
    
    logger.debug(f'{len(disinct_variants)} distinct variants')
    
    hgvs_transcripts = _lookup_hgvs_transcripts(disinct_variants)
    logger.debug(f'{len(hgvs_transcripts)} transcripts from HGVS')
    
    merged_transcripts = _merge_annovar_with_hgvs(annovar_transcripts, hgvs_transcripts, require_match = require_match)
    
    _log_summary(get_summary(require_match, annovar_transcripts, disinct_variants, hgvs_transcripts, merged_transcripts))
    
    return merged_transcripts
    

def _main():
    '''
    main function
    '''
    args = _parse_args()
    
    txEffCsv = TxEffCsv()    
    annovar_transcripts = txEffCsv.read_transcripts(args.in_file.name)
    logger.debug(f'Read {len(annovar_transcripts)} Annovar transcripts from {args.in_file.name}')
    
    merged_transcripts = get_updated_hgvs_transcritpts(annovar_transcripts, args.require_match)
    
    logger.info(f"Writing {args.out_file.name}")
    txEffCsv.write_transcripts(args.out_file.name, merged_transcripts)

if __name__ == '__main__':
    _main()