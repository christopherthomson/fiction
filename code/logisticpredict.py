# logisticpredict.py
#
# Based on logisticleave1out.py which was based on
# parallel_crossvalidate.py from the paceofchange repo.
#
# Reads all volumes meeting a given set of criteria,
# and uses a leave-one-out strategy to distinguish
# reviewed volumes (class 1) from random
# class 0. In cases where an author occurs more
# than once in the dataset, it leaves out all
# volumes by that author whenever making a prediction
# about one of them.
#
# This version differs from parallel_crossvalidate
# in using a different metadata structure, and
# especially a multi-tag folksonomic system for
# identifying the positive and negative classes.
#
# The main class here is create_model().
# It accepts three parameters, each of which is a tuple
# that gets unpacked.
#
# There are unfortunately a lot of details in those tuples,
# because I've written this script to be very flexible and
# permit a lot of different kinds of modeling.
#
# paths unpacks into
# sourcefolder, extension, metadatapath, outputpath, vocabpath
# where
# sourcefolder is the directory with data files
# extension is the extension those files end with
# metadatapath is the path to a metadata csv
# outputpath is the path to a csv of results to be written
# and vocabpath is the path to a file of words to be used
#   as features for all models
#
# exclusions unpacks into
# excludeif, excludeifnot, excludebelow, excludeabove, sizecap
# where
# all the "excludes" are dictionaries pairing a key (the name of a metadata
#     column) with a value that should be excluded -- if it's present,
#     absent, lower than this, or higher than this.
# sizecap limits the number of vols in the positive class; randomly
#      sampled if greater.
#
# classifyconditions unpacks into:
# positive_tags, negative_tags, datetype, numfeatures, regularization, testconditions
# where
# positive_tags is a list of tags to be included in the positive class
# negative_tags is a list of tags to be selected for the negative class
#     (unless volume also has a positive_tag, and note that the negative class
#      is always selected to match the chronological distribution of the positive
#      as closely as possible)
# datetype is the date column to be used for chronological distribution
# numfeatures can be used to limit the features in this model to top N;
#      it is in practice not functional right now because I'm using all
#      features in the vocab file -- originally selected by doc frequency in
#      the whole corpus
# regularization is a constant to be handed to scikit-learn (I'm using one
#    established in previous experiments on a different corpus)
# and testconditions ... is complex.
#
# The variable testconditions will be a set of tags. It may contain tags for classes
# that are to be treated as a test set. Positive volumes will be assigned to
# this set if they have no positive tags that are *not* in testconditions.
# A corresponding group of negative volumes will at the same time
# be assigned. It can also contain two integers to be interpreted as dates, a
# pastthreshold and futurethreshold. Dates outside these thresholds will not
# be used for training. If date thresholds are provided they must be provided
# as a pair to clarify which one is the pastthreshold and which the future.
# If you're only wanting to exclude volumes in the future, provide a past
# threshold like "1."

# All of these conditions exclude volumes from the training set, and place them
# in a set that is used only for testing. But also note that these
# exclusions are always IN ADDITION TO leave-one-out crossvalidation by author.

# In other words, if an author w/ multiple volumes has only some of them excluded
# from training by testconditions, it is *still* the case that the author will never
# be in a training set when her own volumes are being predicted.

import numpy as np
import pandas as pd
import csv, os, random, sys, datetime
from collections import Counter
from multiprocessing import Pool
from sklearn.linear_model import LogisticRegression
import modelingprocess
import metafilter
# from scipy.stats import norm
import matplotlib.pyplot as plt

usedate = False
# Leave this flag false unless you plan major
# surgery to reactivate the currently-deprecated
# option to use "date" as a predictive feature.

# There are three different date types we can use.
# Choose which here.

# FUNCTIONS GET DEFINED BELOW.

def infer_date(metadictentry, datetype):
    if datetype == 'pubdate':
        return metadictentry[datetype]
    elif datetype == 'firstpub':
        firstpub = metadictentry['firstpub']
        if firstpub > 1700 and firstpub < 1950:
            return firstpub
        else:
            return metadictentry['pubdate']
    else:
        sys.exit(0)

def appendif(key, value, dictionary):
    if key in dictionary:
        dictionary[key].append(value)
    else:
        dictionary[key] = [value]

# Clean this up and make it unnecessary.

def dirty_pairtree(htid):
    ''' Changes a 'clean' HathiTrust ID (with only chars that are
    legal in filenames) into a 'clean' version of the same name
    (which may contain illegal chars.)
    '''
    period = htid.find('.')
    prefix = htid[0:period]
    postfix = htid[(period+1): ]
    if '=' in postfix:
        postfix = postfix.replace('+',':')
        postfix = postfix.replace('=','/')
    dirtyname = prefix + "." + postfix
    return dirtyname

def forceint(astring):
    try:
        intval = int(astring)
    except:
        intval = 0

    return intval

def get_features(wordcounts, wordlist):
    numwords = len(wordlist)
    wordvec = np.zeros(numwords)
    for idx, word in enumerate(wordlist):
        if word in wordcounts:
            wordvec[idx] = wordcounts[word]

    return wordvec

# In an earlier version of this script, we sometimes used
# "publication date" as a feature, to see what would happen.
# In the current version, we don't. Some of the functions
# and features remain, but they are deprecated. E.g.:

def get_features_with_date(wordcounts, wordlist, date, totalcount):
    numwords = len(wordlist)
    wordvec = np.zeros(numwords + 1)
    for idx, word in enumerate(wordlist):
        if word in wordcounts:
            wordvec[idx] = wordcounts[word]

    wordvec = wordvec / (totalcount + 0.0001)
    wordvec[numwords] = date
    return wordvec

def sliceframe(dataframe, yvals, excludedrows, testrow):
    numrows = len(dataframe)
    newyvals = list(yvals)
    for i in excludedrows:
        del newyvals[i]
        # NB: This only works if we assume that excluded rows
        # has already been sorted in descending order !!!!!!!

    trainingset = dataframe.drop(dataframe.index[excludedrows])

    newyvals = np.array(newyvals)
    testset = dataframe.iloc[testrow]

    return trainingset, newyvals, testset

def normalizearray(featurearray, usedate):
    '''Normalizes an array by centering on means and
    scaling by standard deviations. Also returns the
    means and standard deviations for features, so that
    they can be pickled.
    '''

    numinstances, numfeatures = featurearray.shape
    means = list()
    stdevs = list()
    lastcolumn = numfeatures - 1
    for featureidx in range(numfeatures):

        thiscolumn = featurearray.iloc[ : , featureidx]
        thismean = np.mean(thiscolumn)

        thisstdev = np.std(thiscolumn)

        if (not usedate) or featureidx != lastcolumn:
            # If we're using date we don't normalize the last column.
            means.append(thismean)
            stdevs.append(thisstdev)
            featurearray.iloc[ : , featureidx] = (thiscolumn - thismean) / thisstdev
        else:
            print('FLAG')
            means.append(thismean)
            thisstdev = 0.1
            stdevs.append(thisstdev)
            featurearray.iloc[ : , featureidx] = (thiscolumn - thismean) / thisstdev
            # We set a small stdev for date.

    return featurearray, means, stdevs

def binormal_select(vocablist, positivecounts, negativecounts, totalpos, totalneg, k):
    ''' A feature-selection option, not currently in use.
    '''
    all_scores = np.zeros(len(vocablist))

    for idx, word in enumerate(vocablist):
        # For each word we create a vector the length of vols in each class
        # that contains real counts, plus zeroes for all those vols not
        # represented.

        positives = np.zeros(totalpos, dtype = 'int64')
        if word in positivecounts:
            positives[0: len(positivecounts[word])] = positivecounts[word]

        negatives = np.zeros(totalneg, dtype = 'int64')
        if word in negativecounts:
            negatives[0: len(negativecounts[word])] = negativecounts[word]

        featuremean = np.mean(np.append(positives, negatives))

        tp = sum(positives > featuremean)
        fp = sum(positives <= featuremean)
        tn = sum(negatives > featuremean)
        fn = sum(negatives <= featuremean)
        tpr = tp/(tp+fn) # true positive ratio
        fpr = fp/(fp+tn) # false positive ratio

        bns_score = abs(norm.ppf(tpr) - norm.ppf(fpr))
        # See Forman

        if np.isinf(bns_score) or np.isnan(bns_score):
            bns_score = 0

        all_scores[idx] = bns_score

    zipped = [x for x in zip(all_scores, vocablist)]
    zipped.sort(reverse = True)
    with open('bnsscores.tsv', mode='w', encoding = 'utf-8') as f:
        for score, word in zipped:
            f.write(word + '\t' + str(score) + '\n')

    return [x[1] for x in zipped[0:k]]

def confirm_testconditions(testconditions, positive_tags):

    if len(testconditions) < 1:
        print('The testconditions set has no elements.')
        sys.exit(0)
    else:
        for elem in testconditions:
            if elem in positive_tags or elem.isdigit():
                # that's fine
                continue
            elif elem == '':
                # also okay
                continue
            else:
                print('Illegal element in testconditions.')
                sys.exit(0)

def get_volume_lists(volumeIDs, volumepaths, IDsToUse, metadict, datetype, positive_tags, testconditions, classdictionary):
    '''
    This function creates an ordered list of volume IDs included in this
    modeling process, and an ordered list of volume-path tuples.

    It also identifies positive volumes that are not to be included in a training set,
    because they belong to a category that is being tested.
    '''

    volspresent = []
    orderedIDs = []
    donttrainset = set()

    for volid, volpath in zip(volumeIDs, volumepaths):
        if volid not in IDsToUse:
            continue
        else:
            volspresent.append((volid, volpath))
            orderedIDs.append(volid)

    thresholds = []
    for elem in testconditions:
        if elem.isdigit():
            thresholds.append(int(elem))

    thresholds.sort()
    if len(thresholds) == 2:
        pastthreshold = thresholds[0]
        futurethreshold = thresholds[1]
    else:
        pastthreshold = 0
        futurethreshold = 3000
        # we are unlikely to have any volumes before or after
        # those dates

    for volid in orderedIDs:
        if classdictionary[volid] != 1:
            continue
            # On the first pass we only add positive volumes
            # to donttrainset. Negative volumes handled in a
            # separate function.

        date = infer_date(metadict[volid], datetype)
        if date < pastthreshold or date > futurethreshold:
            donttrainset.add(volid)
            continue

        tagset = metadict[volid]['tagset']
        hasexclusion = False
        hasotherpositive = False

        for tag in positive_tags:
            if tag in tagset and not tag in testconditions:
                hasotherpositive = True

        for tag in testconditions:
            if tag in tagset:
                hasexclusion = True

        if hasexclusion and not hasotherpositive:
            donttrainset.add(volid)

    return volspresent, orderedIDs, donttrainset

def first_and_last(idset, metadict, datetype):
    min = 3000
    max = 0

    for anid in idset:
        date = metadict[anid][datetype]
        if date < min:
            min = date
        if date > max:
            max = date

    return min, max

def add_matching_negs(donttrainset, orderedIDs, classdictionary, metadict, datetype):

    negatives = []

    for anid in orderedIDs:
        if classdictionary[anid] == 0:
            negatives.append(metadict[anid])

    matching_negatives = []

    print(len(donttrainset))

    for anid in donttrainset:
        this_positive = metadict[anid]
        closest_negative_idx = metafilter.closest_idx(negatives, this_positive, datetype)
        closest_negative = negatives.pop(closest_negative_idx)
        matching_negatives.append(closest_negative['docid'])

    min, max = first_and_last(donttrainset, metadict, datetype)
    if min > 0:
        print("The set of volumes not to be trained on includes " + str(len(donttrainset)))
        print("postive volumes, ranging from " + str(min) + " to " + str(max) + ".")
        print()

    min, max = first_and_last(matching_negatives, metadict, datetype)
    if min > 0:
        print("And also includes " + str(len(matching_negatives)))
        print("negative volumes, ranging from " + str(min) + " to " + str(max) + ".")
        print()

    for negative in matching_negatives:
        donttrainset.add(negative)

    return donttrainset

def get_docfrequency(volspresent, donttrainset):
    '''
    This function counts words in volumes. These wordcounts don't necessarily define
    a feature set for modeling: at present, the limits of that set are defined primarily
    by a fixed list shared across all models (top10k).
    '''

    wordcounts = Counter()

    for volid, volpath in volspresent:
        if volid in donttrainset:
            continue
        else:
            with open(volpath, encoding = 'utf-8') as f:
                for line in f:
                    fields = line.strip().split('\t')
                    if len(fields) > 2 or len(fields) < 2:
                        # this is a malformed line; there are a few of them,
                        # but not enough to be important -- ignore
                        continue
                    word = fields[0]
                    if len(word) > 0 and word[0].isalpha():
                        wordcounts[word] += 1
                        # We're getting docfrequency (the number of documents that
                        # contain this word), not absolute number of word occurrences.
                        # So just add 1 no matter how many times the word occurs.

    return wordcounts

def create_model(paths, exclusions, classifyconditions):
    ''' This is the main function in the module.
    It can be called externally; it's also called
    if the module is run directly.
    '''

    sourcefolder, extension, metadatapath, outputpath, vocabpath = paths
    excludeif, excludeifnot, excludebelow, excludeabove, sizecap = exclusions
    positive_tags, negative_tags, datetype, numfeatures, regularization, testconditions = classifyconditions

    verbose = False

    # The following function confirms that the testconditions are legal.

    confirm_testconditions(testconditions, positive_tags)

    if not sourcefolder.endswith('/'):
        sourcefolder = sourcefolder + '/'

    # This just makes things easier.

    # Get a list of files.
    allthefiles = os.listdir(sourcefolder)
    # random.shuffle(allthefiles)

    volumeIDs = list()
    volumepaths = list()

    for filename in allthefiles:

        if filename.endswith(extension):
            volID = filename.replace(extension, "")
            # The volume ID is basically the filename minus its extension.
            # Extensions are likely to be long enough that there is little
            # danger of accidental occurrence inside a filename. E.g.
            # '.fic.tsv'
            path = sourcefolder + filename
            volumeIDs.append(volID)
            volumepaths.append(path)

    metadict = metafilter.get_metadata(metadatapath, volumeIDs, excludeif, excludeifnot, excludebelow, excludeabove)

    # Now that we have a list of volumes with metadata, we can select the groups of IDs
    # that we actually intend to contrast. If we want to us more or less everything,
    # this may not be necessary. But in some cases we want to use randomly sampled subsets.

    IDsToUse, classdictionary = metafilter.label_classes(metadict, "tagset", positive_tags, negative_tags, sizecap, datetype)

    print()
    min, max = first_and_last(IDsToUse, metadict, datetype)
    if min > 0:
        print("The whole corpus involved here includes " + str(len(IDsToUse)))
        print("volumes, ranging in date from " + str(min) + " to " + str(max) + ".")
        print()

    # We now create an ordered list of id-path tuples for later use, and identify a set of
    # positive ids that should never be used in training.

    volspresent, orderedIDs, donttrainset = get_volume_lists(volumeIDs, volumepaths, IDsToUse, metadict, datetype, positive_tags, testconditions, classdictionary)

    # Extend the set of ids not to be used in training by identifying negative volumes that match
    # the distribution of positive volumes.

    donttrainset = add_matching_negs(donttrainset, orderedIDs, classdictionary, metadict, datetype)

    # Get a count of docfrequency for all words in the corpus. This is probably not needed and
    # might be deprecated later.

    wordcounts = get_docfrequency(volspresent, donttrainset)

    # The feature list we use is defined by the top 10,000 words (by document
    # frequency) in the whole corpus, and it will be the same for all models.
    # However, we don't want to include words that actually occur zero times in
    # the particular set we're modeling. So we check.

    vocablist = []
    ctr = 0
    useall = True

    with open(vocabpath, encoding = 'utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ctr += 1
            if ctr > numfeatures:
                break
                # this allows us to limit how deep we go

            word = row['word'].strip()
            if wordcounts[word] > 2 or useall:
                vocablist.append(word)

    numfeatures = len(vocablist)

    # We need an ordered list of indexes in orderedIDs to exclude.

    donttrainon = [orderedIDs.index(x) for x in donttrainset]

    authormatches = [list(donttrainon) for x in range(len(orderedIDs))]
    # For every index in authormatches, identify a set of indexes that have
    # the same author. Obvs, there will always be at least one.

    # Since we are going to use these indexes to exclude rows, we also add
    # all the ids in donttrainon to every volume

    for idx1, anid in enumerate(orderedIDs):
        thisauthor = metadict[anid]['author']
        for idx2, anotherid in enumerate(orderedIDs):
            otherauthor = metadict[anotherid]['author']
            if thisauthor == otherauthor and not idx2 in authormatches[idx1]:
                authormatches[idx1].append(idx2)

    for alist in authormatches:
        alist.sort(reverse = True)

    # I am reversing the order of indexes so that I can delete them from
    # back to front, without changing indexes yet to be deleted.
    # This will become important in the modelingprocess module.

    volsizes = dict()
    voldata = list()
    classvector = list()

    for volid, volpath in volspresent:

        with open(volpath, encoding = 'utf-8') as f:
            voldict = dict()
            totalcount = 0
            for line in f:
                fields = line.strip().split('\t')
                if len(fields) > 2 or len(fields) < 2:
                    continue

                word = fields[0]
                count = int(fields[1])
                voldict[word] = count
                totalcount += count

        date = infer_date(metadict[volid], datetype)
        date = date - 1700
        if date < 0:
            date = 0

        if usedate:
            features = get_features_with_date(voldict, vocablist, date, totalcount)
            voldata.append(features)
        else:
            features = get_features(voldict, vocablist)
            voldata.append(features / (totalcount + 0.001))


        volsizes[volid] = totalcount
        classflag = classdictionary[volid]
        classvector.append(classflag)

    data = pd.DataFrame(voldata)

    sextuplets = list()
    for i, volid in enumerate(orderedIDs):
        listtoexclude = authormatches[i]
        asixtuple = data, classvector, listtoexclude, i, usedate, regularization
        sextuplets.append(asixtuple)

    # Now do leave-one-out predictions.
    print('Beginning multiprocessing.')

    pool = Pool(processes = 12)
    res = pool.map_async(modelingprocess.model_one_volume, sextuplets)

    # After all files are processed, write metadata, errorlog, and counts of phrases.
    res.wait()
    resultlist = res.get()

    assert len(resultlist) == len(orderedIDs)

    logisticpredictions = dict()
    for i, volid in enumerate(orderedIDs):
        logisticpredictions[volid] = resultlist[i]

    pool.close()
    pool.join()

    print('Multiprocessing concluded.')

    truepositives = 0
    truenegatives = 0
    falsepositives = 0
    falsenegatives = 0
    allvolumes = list()

    with open(outputpath, mode = 'w', encoding = 'utf-8') as f:
        writer = csv.writer(f)
        header = ['volid', 'dateused', 'pubdate', 'birthdate', 'firstpub', 'gender', 'nation', 'allwords', 'logistic', 'realclass', 'author', 'title', 'genretags']
        writer.writerow(header)
        for volid in IDsToUse:
            metadata = metadict[volid]
            dateused = metadata[datetype]
            pubdate = metadata['pubdate']
            birthdate = metadata['birthdate']
            firstpub = metadata['firstpub']
            gender = metadata['gender']
            nation = metadata['nation']
            author = metadata['author']
            title = metadata['title']
            allwords = volsizes[volid]
            logistic = logisticpredictions[volid]
            realclass = classdictionary[volid]
            genretags = ' | '.join(metadata['tagset'])
            outrow = [volid, dateused, pubdate, birthdate, firstpub, gender, nation, allwords, logistic, realclass, author, title, genretags]
            writer.writerow(outrow)
            allvolumes.append(outrow)

            if logistic > 0.5 and classdictionary[volid] > 0.5:
                truepositives += 1
            elif logistic <= 0.5 and classdictionary[volid] < 0.5:
                truenegatives += 1
            elif logistic <= 0.5 and classdictionary[volid] > 0.5:
                falsenegatives += 1
            elif logistic > 0.5 and classdictionary[volid] < 0.5:
                falsepositives += 1

    donttrainon.sort(reverse = True)
    trainingset, yvals, testset = sliceframe(data, classvector, donttrainon, 0)
    trainingset, testset = modelingprocess.remove_zerocols(trainingset, testset)
    newmodel = LogisticRegression(C = regularization)
    trainingset, means, stdevs = normalizearray(trainingset, usedate)
    newmodel.fit(trainingset, yvals)

    coefficients = newmodel.coef_[0] * 100

    coefficientuples = list(zip(coefficients, (coefficients / np.array(stdevs)), vocablist + ['pub.date']))
    coefficientuples.sort()
    if verbose:
        for coefficient, normalizedcoef, word in coefficientuples:
            print(word + " :  " + str(coefficient))

    print()
    accuracy = (truepositives + truenegatives) / len(IDsToUse)

    coefficientpath = outputpath.replace('.csv', '.coefs.csv')
    with open(coefficientpath, mode = 'w', encoding = 'utf-8') as f:
        writer = csv.writer(f)
        for triple in coefficientuples:
            coef, normalizedcoef, word = triple
            writer.writerow([word, coef, normalizedcoef])

    return accuracy, allvolumes, coefficientuples

def diachronic_tilt(allvolumes, modeltype, datelimits):
    ''' Takes a set of predictions produced by a model that knows nothing about date,
    and divides it along a line with a diachronic tilt. We need to do this in a way
    that doesn't violate crossvalidation. I.e., we shouldn't "know" anything
    that the model didn't know. We tried a couple of different ways to do this, but
    the simplest and actually most reliable is to divide the whole dataset along a
    linear central trend line for the data!
    '''

    listofrows = list()
    classvector = list()

    # DEPRECATED
    # if modeltype == 'logistic' and len(datelimits) == 2:
    #     # In this case we construct a subset of data to model on.
    #     tomodeldata = list()
    #     tomodelclasses = list()
    #     pastthreshold, futurethreshold = datelimits

    for volume in allvolumes:
        date = volume[1]
        logistic = volume[8]
        realclass = volume[9]
        listofrows.append([logistic, date])
        classvector.append(realclass)

        # DEPRECATED
        # if modeltype == 'logistic' and len(datelimits) == 2:
        #     if date >= pastthreshold and date <= futurethreshold:
        #         tomodeldata.append([logistic, date])
        #         tomodelclasses.append(realclass)

    y, x = [a for a in zip(*listofrows)]
    plt.axis([min(x) - 2, max(x) + 2, min(y) - 0.02, max(y) + 0.02])
    reviewedx = list()
    reviewedy = list()
    randomx = list()
    randomy = list()

    for idx, reviewcode in enumerate(classvector):
        if reviewcode == 1:
            reviewedx.append(x[idx])
            reviewedy.append(y[idx])
        else:
            randomx.append(x[idx])
            randomy.append(y[idx])

    plt.plot(reviewedx, reviewedy, 'ro')
    plt.plot(randomx, randomy, 'k+')

    if modeltype == 'logistic':
        # all this is DEPRECATED
        print("Hey, you're attempting to use the logistic-tilt option")
        print("that we deactivated. Go in and uncomment the code.")

        # if len(datelimits) == 2:
        #     data = pd.DataFrame(tomodeldata)
        #     responsevariable = tomodelclasses
        # else:
        #     data = pd.DataFrame(listofrows)
        #     responsevariable = classvector

        # newmodel = LogisticRegression(C = 100000)
        # newmodel.fit(data, responsevariable)
        # coefficients = newmodel.coef_[0]

        # intercept = newmodel.intercept_[0] / (-coefficients[0])
        # slope = coefficients[1] / (-coefficients[0])

        # p = np.poly1d([slope, intercept])

    elif modeltype == 'linear':
        # what we actually do

        z = np.polyfit(x, y, 1)
        p = np.poly1d(z)
        slope = z[0]
        intercept = z[1]

    plt.plot(x,p(x),"b-")
    plt.show()

    x = np.array(x, dtype='float64')
    y = np.array(y, dtype='float64')
    classvector = np.array(classvector)
    dividingline = intercept + (x * slope)
    predicted_as_reviewed = (y > dividingline)
    really_reviewed = (classvector == 1)

    accuracy = sum(predicted_as_reviewed == really_reviewed) / len(classvector)

    return accuracy

if __name__ == '__main__':

    # If this class is called directly, it creates a single model using the default
    # settings set below.

    ## PATHS.

    # sourcefolder = '/Users/tunder/Dropbox/GenreProject/python/reception/fiction/texts/'
    # extension = '.fic.tsv'
    # metadatapath = '/Users/tunder/Dropbox/GenreProject/python/reception/fiction/masterficmeta.csv'
    # outputpath = '/Users/tunder/Dropbox/GenreProject/python/reception/fiction/predictions.csv'

    sourcefolder = '../newdata/'
    extension = '.fic.tsv'
    metadatapath = '../meta/genremeta.csv'
    vocabpath = '../lexicon/top10k.csv'

    modelname = input('Name of model? ')
    outputpath = '../results/' + modelname + str(datetime.date.today()) + '.csv'

    # We can simply exclude volumes from consideration on the basis on any
    # metadata category we want, using the dictionaries defined below.

    ## EXCLUSIONS.

    excludeif = dict()
    excludeifnot = dict()
    excludeabove = dict()
    excludebelow = dict()

    excludebelow['firstpub'] = 1700
    excludeabove['firstpub'] = 2000
    sizecap = 1000

    # CLASSIFY CONDITIONS

    # We ask the user for a list of categories to be included in the positive
    # set, as well as a list for the negative set. Default for the negative set
    # is to include all the "random"ly selected categories. Note that random volumes
    # can also be tagged with various specific genre tags; they are included in the
    # negative set only if they lack tags from the positive set.

    tagphrase = input("Comma-separated list of tags to include in the positive class: ")
    positive_tags = [x.strip() for x in tagphrase.split(',')]
    tagphrase = input("Comma-separated list of tags to include in the negative class: ")

    # An easy default option.
    if tagphrase == 'r':
        negative_tags = ['random', 'grandom', 'chirandom']
    else:
        negative_tags = [x.strip() for x in tagphrase.split(',')]

    # We also ask the user to specify categories of texts to be used only for testing.
    # These exclusions from training are in addition to ordinary crossvalidation.

    print()
    print("You can also specify positive tags to be excluded from training, and/or a pair")
    print("of integer dates outside of which vols should be excluded from training.")
    testphrase = input("Comma-separated list of such tags: ")
    testconditions = set([x.strip() for x in testphrase.split(',') if len(x) > 0])

    datetype = "firstpub"
    numfeatures = 10000
    regularization = .000075

    paths = (sourcefolder, extension, metadatapath, outputpath, vocabpath)
    exclusions = (excludeif, excludeifnot, excludebelow, excludeabove, sizecap)
    classifyconditions = (positive_tags, negative_tags, datetype, numfeatures, regularization, testconditions)

    rawaccuracy, allvolumes, coefficientuples = create_model(paths, exclusions, classifyconditions)

    print('If we divide the dataset with a horizontal line at 0.5, accuracy is: ', str(rawaccuracy))
    tiltaccuracy = diachronic_tilt(allvolumes, 'linear', [])

    print("Divided with a line fit to the data trend, it's ", str(tiltaccuracy))
