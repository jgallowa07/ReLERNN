"""
Predicts the recombination rate for all genomic windows along the chromosomes
using a GRU network trained in ReLERNN_TRAIN.py
"""


import os,sys
relernnBase = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),"scripts")
sys.path.insert(1, relernnBase)

from Imports import *
from Simulator import *
from Helpers import *
from SequenceBatchGenerator import *
from Networks import *


def get_index(pos, winSize):
    y=snps_per_win(pos,winSize)
    st=0
    indices=[]
    for i in range(len(y)):
        indices.append([st,st+y[i]])
        st+=y[i]
    return indices


def snps_per_win(pos, window_size):
    bins = np.arange(1, pos.max()+window_size, window_size) #use 1-based coordinates, per VCF standard
    y,x = np.histogram(pos,bins=bins)
    return y


def find_win_size(winSize,pos):
    snpsWin=snps_per_win(pos,winSize)
    mn,u,mx = snpsWin.min(), int(snpsWin.mean()), snpsWin.max()
    if mx <= 1600:
        return [winSize,mn,u,mx,len(snpsWin)]
    else:
        return [mn,u,mx]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vcf',dest='vcf',help='Filtered and QC-checked VCF file Note: Every row must correspond to a biallelic SNP with no missing data)')
    parser.add_argument('--projectDir',dest='outDir',help='Directory for all project output. NOTE: the same projectDir must be used for all functions of ReLERNN')
    parser.add_argument('--gpuID',dest='gpuID',help='Identifier specifying which GPU to use', type=int, default=0)
    args = parser.parse_args()

    ## Set up the directory structure to store the simulations data.
    DataDir = args.outDir
    trainDir = os.path.join(DataDir,"train")
    valiDir = os.path.join(DataDir,"vali")
    testDir = os.path.join(DataDir,"test")
    networkDir = os.path.join(DataDir,"networks")
    vcfDir = os.path.join(DataDir,"splitVCFs")
    modelSave = os.path.join(networkDir,"model.json")
    weightsSave = os.path.join(networkDir,"weights.h5")


    ## Read in the window sizes
    wins=[]
    winFILE=os.path.join(networkDir,"windowSizes.txt")
    with open(winFILE, "r") as fIN:
        for line in fIN:
            ar=line.split()
            wins.append([ar[0],int(ar[1]),int(ar[2]),int(ar[3]),int(ar[4]),int(ar[5])])
    nSam=[]
    maxMean=0
    maxLen=0
    maxMax=0
    for i in range(len(wins)):
        maxMax=max([maxMax,wins[i][5]])
        maxMean=max([maxMean,wins[i][4]])
        maxLen=max([maxLen,wins[i][2]])
        nSam.append(wins[i][1])


    ## Loop through chromosomes and predict
    for i in range(len(wins)):
        ## Read in the hdf5
        bn=os.path.basename(args.vcf)
        h5FILE=os.path.join(vcfDir,bn.replace(".vcf","_%s.hdf5" %(wins[i][0])))
        print("""Importing HDF5: "%s"...""" %(h5FILE))
        callset=h5py.File(h5FILE, mode="r")
        var=allel.VariantChunkedTable(callset["variants"],names=["CHROM","POS"], index="POS")
        chroms=var["CHROM"]
        pos=var["POS"]
        genos=allel.GenotypeChunkedArray(callset["calldata"]["GT"])

        #Is this a haploid or diploid VCF?
        GT=genos.to_haplotypes()
        GT=GT[:,1:2]
        GT=GT[0].tolist()
        if len(set(GT)) == 1 and GT[0] == -1:
            nSamps=len(genos[0])
            hap=True
        else:
            nSamps=len(genos[0])*2
            hap=False


        ## Identify padding required
        maxSegSites = 0
        for ds in [trainDir,valiDir,testDir]:
            DsInfoDir = pickle.load(open(os.path.join(ds,"info.p"),"rb"))
            segSitesInDs = max(DsInfoDir["segSites"])
            maxSegSites = max(maxSegSites,segSitesInDs)
        maxSegSites = max(maxSegSites, maxMax)


        ## Identify parameters used to train
        DsInfoDir = pickle.load(open(os.path.join(trainDir,"info.p"),"rb"))
        winSize=wins[i][2]
        ip=find_win_size(winSize,pos)


        ## Set network parameters
        bds_pred_params = {
            'INFO':DsInfoDir,
            'CHROM':chroms[0],
            'WIN':winSize,
            'IDs':get_index(pos,winSize),
            'GT':genos,
            'POS':pos,
            'batchSize': ip[4],
            'maxLen': maxSegSites,
            'frameWidth': 5,
            'sortInds':False,
            'center':False,
            'ancVal':-1,
            'padVal':0,
            'derVal':1,
            'realLinePos':True,
            'posPadVal':0,
            'hap':hap
                  }


        ### Define sequence batch generator
        pred_sequence = VCFBatchGenerator(**bds_pred_params)


        ## Load trained model and make predictions on VCF data
        pred_resultFile = os.path.join(DataDir,wins[i][0]+".CHPREDICT.txt")
        load_and_predictVCF(VCFGenerator=pred_sequence,
                resultsFile=pred_resultFile,
                network=[modelSave,weightsSave],
                gpuID=args.gpuID)


    ## Combine chromosome predictions in whole genome prediction file and rm chromosome files
    genPredFILE=os.path.join(DataDir,bn.replace(".vcf",".PREDICT.txt"))
    files=[]
    for f in glob.glob(os.path.join(DataDir,"*.CHPREDICT.txt")):
        files.append(f)
    ct=0
    with open(genPredFILE, "w") as fOUT:
        for f in sorted(files):
            if ct==0:
                with open(f, "r") as fIN:
                    for line in fIN:
                        fOUT.write(line)
            else:
                with open(f, "r") as fIN:
                    fIN.readline()
                    for line in fIN:
                        fOUT.write(line)
            ct+=1
            cmd="rm %s" %(f)
            os.system(cmd)


    print("\n***ReLERNN_PREDICT.py FINISHED!***\n")


if __name__ == "__main__":
	main()
