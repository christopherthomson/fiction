import logisticpredict

def ghastly_stew():

    ## PATHS.

    sourcefolder = '../newdata/'
    extension = '.fic.tsv'
    metadatapath = '../meta/finalmeta.csv'
    vocabpath = '../lexicon/new10k.csv'

    modelname = 'ghastlystew'
    outputpath = '../results/' + modelname + str(datetime.date.today()) + '.csv'

    # We can simply exclude volumes from consideration on the basis on any
    # metadata category we want, using the dictionaries defined below.

    ## EXCLUSIONS.

    excludeif = dict()
    excludeifnot = dict()
    excludeabove = dict()
    excludebelow = dict()

    excludebelow['firstpub'] = 1700
    excludeabove['firstpub'] = 2020

    allstewgenres = {'cozy', 'hardboiled', 'det100', 'chimyst', 'locdetective', 'lockandkey', 'crime', 'locdetmyst', 'blcrime', 'anatscifi', 'locscifi', 'chiscifi', 'femscifi', 'stangothic', 'pbgothic', 'lochorror', 'chihorror', 'locghost'}

    # We have to explicitly exclude genres because the category "stew" in the
    # positive category wouldn't otherwise automatically exclude the constituent
    # tags that were used to create it.

    # I would just have put all those tags in the positive tag list, but then you'd lose
    # the ability to explicitly balance equal numbers of crime, gothic,
    # and science fiction, plus sensation novels. You'd get a list dominated by
    # the crime categories, which are better-represented in the dataset.

    excludeif['negatives'] = allstewgenres
    sizecap = 250

    # CLASSIFY CONDITIONS

    # We ask the user for a list of categories to be included in the positive
    # set, as well as a list for the negative set. Default for the negative set
    # is to include all the "random"ly selected categories. Note that random volumes
    # can also be tagged with various specific genre tags; they are included in the
    # negative set only if they lack tags from the positive set.

    positive_tags = ['stew']
    negative_tags = ['random', 'chirandom']
    testconditions = set()

    datetype = "firstpub"
    numfeatures = 10000
    regularization = .000075

    paths = (sourcefolder, extension, metadatapath, outputpath, vocabpath)
    exclusions = (excludeif, excludeifnot, excludebelow, excludeabove, sizecap)
    classifyconditions = (positive_tags, negative_tags, datetype, numfeatures, regularization, testconditions)

    rawaccuracy, allvolumes, coefficientuples = logisticpredict.create_model(paths, exclusions, classifyconditions)

    print('If we divide the dataset with a horizontal line at 0.5, accuracy is: ', str(rawaccuracy))

def make_paths(modelname):
    '''
    Makes a pathtuple using a model name and a default set of
    paths to feature-vocab and metadata files.
    '''

    sourcefolder = '../newdata/'
    extension = '.fic.tsv'
    metadatapath = '../meta/finalmeta.csv'
    vocabpath = '../lexicon/new10k.csv'
    # These words will be used as features

    outputpath = '../results/' + modelname + str(datetime.date.today()) + '.csv'

    return (sourcefolder, extension, metadatapath, outputpath, vocabpath)

def make_exclusions(startdate, enddate, sizecap):
    excludeif = dict()
    excludeifnot = dict()
    excludeabove = dict()
    excludebelow = dict()

    excludebelow['firstpub'] = startdate
    excludeabove['firstpub'] = enddate

    return (excludeif, excludeifnot, excludebelow, excludeabove, sizecap)

def project_detective_beyond_date(dividedate):

    divide_date = 1920
    sizecap = 250

    modelname = 'detectivejustpost1920'
    paths = make_paths(modelname)
    sourcefolder, extension, metadatapath, outputpath, vocabpath = paths

    # We can simply exclude volumes from consideration on the basis on any
    # metadata category we want, using the dictionaries defined below.

    ## EXCLUSIONS.

    exclusions = make_exclusions(1700, dividedate, sizecap)

    positive_tags = ['locdetective', 'locdetmyst', 'chimyst', 'locdetmyst', 'det100']
    negative_tags = ['random', 'chirandom']
    testconditions = set()

    datetype = "firstpub"
    numfeatures = 10000
    regularization = .000075

    classifyconditions = (positive_tags, negative_tags, datetype, numfeatures, regularization, testconditions)

    rawaccuracy, allvolumes, coefficientuples = logisticpredict.create_model(paths, exclusions, classifyconditions)

    print('If we divide the dataset with a horizontal line at 0.5, accuracy is: ', str(rawaccuracy))
