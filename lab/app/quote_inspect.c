/* Structural decoding only; signatures are checked independently by tpm2_checkquote. */
#include <tss2/tss2_mu.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  FILE *file=fopen(argv[1],"rb");if(!file)return 1;
  uint8_t bytes[4097];size_t size=fread(bytes,1,sizeof bytes,file);
  int io_error=ferror(file);if(fclose(file))io_error=1;
  if(io_error || size>4096)return 1;
  TPMS_ATTEST attestation={0};size_t offset=0;
  if(Tss2_MU_TPMS_ATTEST_Unmarshal(bytes,size,&offset,&attestation)!=TSS2_RC_SUCCESS || offset!=size ||
     attestation.magic!=TPM2_GENERATED_VALUE || attestation.type!=TPM2_ST_ATTEST_QUOTE ||
     attestation.extraData.size!=32 || attestation.attested.quote.pcrDigest.size!=32)return 1;
  const TPML_PCR_SELECTION *selection=&attestation.attested.quote.pcrSelect;
  int matches=selection->count==1 && selection->pcrSelections[0].hash==TPM2_ALG_SHA256 &&
      selection->pcrSelections[0].sizeofSelect==3 && selection->pcrSelections[0].pcrSelect[0]==0x81 &&
      selection->pcrSelections[0].pcrSelect[1]==0 && selection->pcrSelections[0].pcrSelect[2]==0;
  int matches10=selection->count==1 && selection->pcrSelections[0].hash==TPM2_ALG_SHA256 &&
      selection->pcrSelections[0].sizeofSelect==3 && selection->pcrSelections[0].pcrSelect[0]==0 &&
      selection->pcrSelections[0].pcrSelect[1]==4 && selection->pcrSelections[0].pcrSelect[2]==0;
  printf("{\"pcr10_selection_matches\":%s,",matches10?"true":"false");
  printf("\"parsed\":true,\"pcr_selection_matches\":%s,\"qualification\":\"",matches?"true":"false");
  for(size_t i=0;i<attestation.extraData.size;++i)printf("%02x",attestation.extraData.buffer[i]);
  printf("\",\"cryptographic_validity\":\"not_verified\"}\n");
  return fflush(stdout)==EOF?1:0;
}
