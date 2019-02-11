# ----------------------------------------------------------------------
# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2019, Numenta, Inc.  Unless you have an agreement
# with Numenta, Inc., for a separate license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

from __future__ import print_function

import math
import time
from multiprocessing import Pool

import torch

import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Need to run it from htmresearch top level:
# python projects/sdr_paper/pytorch_experiments/analyze_model.py model_path


def getSparseTensor(numNonzeros, inputSize, outputSize,
                    onlyPositive=False,
                    fixedRange=1.0/24):
  """
  Return a random tensor that is initialized like a weight matrix
  Size is outputSize X inputSize, where weightSparsity% of each row is non-zero
  """
  # Initialize weights in the typical fashion.
  w = torch.Tensor(outputSize, inputSize, )

  if onlyPositive:
    w.data.uniform_(0, fixedRange)
  else:
    w.data.uniform_(-fixedRange, fixedRange)

  # Zero out weights for sparse weight matrices
  if numNonzeros < inputSize:
    numZeros = inputSize - numNonzeros

    outputIndices = np.arange(outputSize)
    inputIndices = np.array([np.random.permutation(inputSize)[:numZeros]
                             for _ in outputIndices], dtype=np.long)

    # Create tensor indices for all non-zero weights
    zeroIndices = np.empty((outputSize, numZeros, 2), dtype=np.long)
    zeroIndices[:, :, 0] = outputIndices[:, None]
    zeroIndices[:, :, 1] = inputIndices
    zeroIndices = torch.LongTensor(zeroIndices.reshape(-1, 2))

    zeroWts = (zeroIndices[:, 0], zeroIndices[:, 1])
    w.data[zeroWts] = 0.0

  return w


def getPermutedTensors(W, kw, n, m2, noisePct):
  """
  Generate m2 noisy versions of W. Noisy
  version of W is generated by randomly permuting noisePct of the non-zero
  components to other components.

  :param W:
  :param n:
  :param m2:
  :param noisePct:

  :return:
  """
  W2 = W.repeat(m2, 1)
  nz = W[0].nonzero()
  numberToZero = int(round(noisePct * kw))
  for i in range(m2):
    indices = np.random.permutation(kw)[0:numberToZero]
    for j in indices:
      W2[i,nz[j]] = 0
  return W2


def plotDot(dot, title="Histogram of dot products",
            path="dot.pdf"):
  bins = np.linspace(dot.min(), dot.max(), 100)
  plt.hist(dot, bins, alpha=0.5, label='All cols')
  plt.title(title)
  plt.xlabel("Dot product")
  plt.ylabel("Number")
  plt.savefig(path)
  plt.close()

# def conv_output_shape(h_w, kernel_size=1, stride=1, pad=0, dilation=1):
#   """
#   Utility function for computing output of convolutions
#   takes a tuple of (h,w) and returns a tuple of (h,w)
#   """
#   if type(kernel_size) is not tuple:
#       kernel_size = (kernel_size, kernel_size)
#   h = floor( ((h_w[0] + (2 * pad) - ( dilation * (kernel_size[0] - 1) ) - 1 )/ stride) + 1)
#   w = floor( ((h_w[1] + (2 * pad) - ( dilation * (kernel_size[1] - 1) ) - 1 )/ stride) + 1)
#   return h, w


def getTheta(k, nTrials=100000):
  """
  Estimate a reasonable value of theta for this k.
  """
  theDots = np.zeros(nTrials)
  w1 = getSparseTensor(k, k, nTrials, fixedRange=1.0/k)
  for i in range(nTrials):
    theDots[i] = w1[i].dot(w1[i])

  dotMean = theDots.mean()
  print("k=", k, "min/mean/max diag of w dot products",
        theDots.min(), dotMean, theDots.max())

  theta = dotMean / 2.0
  print("Using theta as mean / 2.0 = ", theta)

  return theta, theDots


def returnMatches(kw, kv, n, theta, inputScaling=1.0):
  """
  :param kw: k for the weight vectors
  :param kv: k for the input vectors
  :param n:  dimensionality of input vector
  :param theta: threshold for matching after dot product

  :return: percent that matched, number that matched, total match comparisons
  """
  # How many prototypes to store
  m1 = 2
  m2 = 1000

  weights = getSparseTensor(kw, n, m1, fixedRange=1.0 / kw )

  # Initialize random input vectors using given scaling and see how many match
  inputVectors = getSparseTensor(kv, n, m2,
                                 onlyPositive=True,
                                 fixedRange=inputScaling / kw,
                                 )
  dot = inputVectors.matmul(weights.t())
  numMatches = ((dot >= theta).sum()).item()
  pctMatches = numMatches / float(m1*m2)

  # plotDot(dot,
  #         title="Histogram of overlaps 100 out of 2000",
  #         path="dot_100_2000.pdf")

  return pctMatches, numMatches, m1*m2


def returnFalseNegatives(kw, noisePct, n, theta):
  """
  Generate a weight vector W, with kw non-zero components. Generate 1000
  noisy versions of W and return the match statistics. Noisy version of W is
  generated by randomly setting noisePct of the non-zero components to zero.

  :param kw: k for the weight vectors
  :param noisePct: percent noise, from 0 to 1
  :param n:  dimensionality of input vector
  :param theta: threshold for matching after dot product

  :return: percent that matched, number that matched, total match comparisons
  """

  W = getSparseTensor(kw, n, 1, fixedRange=1.0 / kw)

  # Get permuted versions of W and see how many match
  m2 = 10
  inputVectors = getPermutedTensors(W, kw, n, m2, noisePct)
  dot = inputVectors.matmul(W.t())

  numMatches = ((dot >= theta).sum()).item()
  pctMatches = numMatches / float(m2)

  return pctMatches, numMatches, m2


def computeFalseNegatives(args):
  n = args["n"]
  kw = args["kw"]
  noisePct = args["noisePct"]
  nTrials = args["nTrials"]

  theta, _ = getTheta(kw)

  numMatches = 0
  totalComparisons = 0
  for t in range(nTrials):
    pct, num, total = returnFalseNegatives(kw, noisePct, n, theta)
    numMatches += num
    totalComparisons += total

  pctFalseNegatives = 1.0 - float(numMatches) / totalComparisons
  print("kw, n, noise:", kw, n, noisePct,
        ", matches:", numMatches,
        ", comparisons:", totalComparisons,
        ", pct false negatives:", pctFalseNegatives)

  args.update({"pctFalse": pctFalseNegatives})

  return args


def computeFalseNegativesParallel(
            listofNoise=[0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8],
            kw=24,
            numWorkers=8,
            nTrials=1000,
            n=500,
            ):

  print("Computing match probabilities for kw=", kw)

  # Create arguments for the possibilities we want to test
  args = []
  for ni, noise in enumerate(listofNoise):
    args.append({
        "kw": kw, "n": n,
        "noisePct": noise,
        "nTrials": nTrials,
        "errorIndex": ni,
        })

  numExperiments = len(args)
  if numWorkers > 1:
    pool = Pool(processes=numWorkers)
    rs = pool.map_async(computeFalseNegatives, args, chunksize=1)
    while not rs.ready():
      remaining = rs._number_left
      pctDone = 100.0 - (100.0*remaining) / numExperiments
      print("    =>", remaining,
            "experiments remaining, percent complete=",pctDone)
      time.sleep(5)
    pool.close()  # No more work
    pool.join()
    result = rs.get()
  else:
    result = []
    for arg in args:
      result.append(computeFalseNegatives(arg))

  # Read out results and store in numpy array for plotting
  errors = np.zeros(len(listofNoise))
  for r in result:
    errors[r["errorIndex"]] = r["pctFalse"]

  print("Errors for kw=", kw)
  print(errors)
  plotFalseMatches(listofNoise, errors,kw,
              "images/scalar_false_matches_kw" + str(kw) + ".pdf")


def computeMatchProbability(args):
  """
  Runs a number of trials of returnMatches() and returns an overall probability
  of matches given the parameters.

  :param args is a dictionary containing the following keys:

  kw: k for the weight vectors

  kv: k for the input vectors. If -1, kv is set to n/2

  n:  dimensionality of input vector

  theta: threshold for matching after dot product

  nTrials: number of trials to run

  inputScaling: scale factor for the input vectors. 1.0 means the scaling
    is the same as the stored weight vectors.

  :return: args updated with the percent that matched
  """
  kv = args["k"]
  n = args["n"]
  kw = args["kw"]
  theta = args["theta"]

  if kv == -1:
    kv = int(round(n/2.0))

  numMatches = 0
  totalComparisons = 0
  for t in range(args["nTrials"]):
    pct, num, total = returnMatches(kw, kv, n, theta, args["inputScaling"])
    numMatches += num
    totalComparisons += total

  pctMatches = float(numMatches) / totalComparisons
  print("kw, kv, n, s:", kw, kv, n, args["inputScaling"],
        ", matches:", numMatches,
        ", comparisons:", totalComparisons,
        ", pct matches:", pctMatches)

  args.update({"pctMatches": pctMatches})

  return args


def computeMatchProbabilityParallel(args, numWorkers=8):
  numExperiments = len(args)
  if numWorkers > 1:
    pool = Pool(processes=numWorkers)
    rs = pool.map_async(computeMatchProbability, args, chunksize=1)
    while not rs.ready():
      remaining = rs._number_left
      pctDone = 100.0 - (100.0*remaining) / numExperiments
      print("    =>", remaining,
            "experiments remaining, percent complete=",pctDone)
      time.sleep(5)
    pool.close()  # No more work
    pool.join()
    result = rs.get()
  else:
    result = []
    for arg in args:
      result.append(computeMatchProbability(arg))

  return result


def computeMatchProbabilities(listofkValues=[64, 128, 256, -1],
                              listofNValues=[250, 500, 1000, 1500, 2000, 2500],
                              inputScale=2.0,
                              kw=24,
                              numWorkers=8,
                              nTrials=1000,
                              ):

  print("Computing match probabilities for input scale=", inputScale)

  # Create arguments for the possibilities we want to test
  args = []
  theta, _ = getTheta(kw)
  for ki, k in enumerate(listofkValues):
    for ni, n in enumerate(listofNValues):
      args.append({
          "k": k, "kw": kw, "n": n, "theta": theta,
          "nTrials": nTrials, "inputScaling": 1.0,
          "errorIndex": [ki, ni],
          })

  result = computeMatchProbabilityParallel(args, numWorkers)


  # Read out results and store in numpy array for plotting
  errors = np.zeros((len(listofkValues), len(listofNValues)))
  for r in result:
    errors[r["errorIndex"][0], r["errorIndex"][1]] = r["pctMatches"]

  print("Errors for kw=", kw)
  print(errors)
  plotMatches(listofkValues, listofNValues, errors,
              "images/scalar_effect_of_n_kw" + str(kw) + ".pdf")


def computeScaledProbabilities(listOfScales=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
                               listofkValues=[64, 128, 256],
                               kw=32,
                               n=1000,
                               numWorkers=8,
                               nTrials=1000,
                               ):
  # Create arguments for the possibilities we want to test
  args = []
  theta, _ = getTheta(kw)
  for ki, k in enumerate(listofkValues):
    for si, s in enumerate(listOfScales):
      args.append({
          "k": k, "kw": kw, "n": n, "theta": theta,
          "nTrials": nTrials, "inputScaling": s,
          "errorIndex": [ki, si],
          })

  result = computeMatchProbabilityParallel(args, numWorkers)

  errors = np.zeros((len(listofkValues), len(listOfScales)))
  for r in result:
    errors[r["errorIndex"][0], r["errorIndex"][1]] = r["pctMatches"]

  print("Errors using scaled inputs, for kw=", kw)
  print(errors)
  plotScaledMatches(listofkValues, listOfScales, errors,
              "images/scalar_effect_of_scale_kw" + str(kw) + ".pdf")


  # Nice errors using scaled inputs, for kw= 32 and nTrials=6000 (12,000,000
  # matches per datapoint.
  listOfScales = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
  listofkValues = [64, 128, 256]
  kw = 32
  errors = np.array([
        [0.00000000e+00, 0.00000000e+00, 0.00000000e+00, 2.50000000e-07,
         2.58333333e-06, 2.13333333e-05, 8.45833333e-05, 2.52750000e-04],
        [0.00000000e+00, 0.00000000e+00, 2.50000000e-07, 9.66666667e-06,
         7.62500000e-05, 3.23666667e-04, 9.75666667e-04, 2.22650000e-03],
        [0.00000000e+00, 6.66666667e-07, 2.89166667e-05, 2.93000000e-04,
         1.29500000e-03, 3.71925000e-03, 7.98591667e-03, 1.42828333e-02]
  ])
  plotScaledMatches(listofkValues, listOfScales, errors,
                    "images/scalar_effect_of_scale_kw" + str(kw) + ".pdf")


def plotMatches(listofKValues, listofNValues, errors,
                fileName = "images/scalar_effect_of_n.pdf"):
  fig, ax = plt.subplots()

  fig.suptitle("Prob. of matching a sparse random input")
  ax.set_xlabel("Dimensionality (n)")
  ax.set_ylabel("Frequency of matches")
  ax.set_yscale("log")

  ax.plot(listofNValues, errors[0,:], 'k:',
          label="a=64 (predicted)", marker="o", color='black')
  ax.plot(listofNValues, errors[1,:], 'k:',
          label="a=128 (predicted)", marker="o", color='black')
  ax.plot(listofNValues, errors[2,:], 'k:',
          label="a=256 (predicted)", marker="o", color='black')
  ax.plot(listofNValues, errors[3,:], 'k:',
          label="a=n/2 (predicted)", marker="o", color='black')

  ax.annotate(r"$a = 64$", xy=(listofNValues[3]+100, errors[0,3]),
              xytext=(-5, 2), textcoords="offset points", ha="left",
              color='black')
  ax.annotate(r"$a = 128$", xy=(listofNValues[3]+100, errors[1,3]),
               ha="left", color='black')
  ax.annotate(r"$a = 256$", xy=(listofNValues[3]+100, errors[2,3]),
               ha="left", color='black')
  ax.annotate(r"$a = \frac{n}{2}$", xy=(listofNValues[3]+100, errors[3,3]),
               ha="left", color='black')

  plt.minorticks_off()
  plt.grid(True, alpha=0.3)

  plt.savefig(fileName)
  plt.close()


def plotScaledMatches(listofKValues, listOfScales, errors,
                fileName = "images/scalar_effect_of_scale.pdf"):
  fig, ax = plt.subplots()

  fig.suptitle("Prob. of matching a sparse random input")
  ax.set_xlabel("Scale factor (s)")
  ax.set_ylabel("Frequency of matches")
  ax.set_yscale("log")

  ax.plot(listOfScales, errors[0, :], 'k:',
          label="a=64 (predicted)", marker="o", color='black')
  ax.plot(listOfScales, errors[1, :], 'k:',
          label="a=128 (predicted)", marker="o", color='black')
  ax.plot(listOfScales, errors[2, :], 'k:',
          label="a=128 (predicted)", marker="o", color='black')


  ax.annotate(r"$a = 64$", xy=(listOfScales[3]+0.2, errors[0, 3]),
              xytext=(-5, 2), textcoords="offset points", ha="left",
              color='black')
  ax.annotate(r"$a = 128$", xy=(listOfScales[3]+0.2, errors[1, 3]),
               ha="left", color='black')
  ax.annotate(r"$a = 256$", xy=(listOfScales[3]+0.2, errors[2, 3]),
               ha="left", color='black')

  plt.minorticks_off()
  plt.grid(True, alpha=0.3)

  plt.savefig(fileName)
  plt.close()


def plotThetaDistribution(kw, fileName = "images/theta_distribution.pdf"):
  theta, theDots = getTheta(kw)

  # Plot histogram of overlaps
  bins = np.linspace(float(theDots.min()), float(theDots.max()), 50)
  plt.hist(theDots, bins, alpha=0.5, label='Dot products')
  plt.legend(loc='upper right')
  plt.xlabel("Dot product")
  plt.ylabel("Frequency")
  plt.title("Distribution of dot products, kw=" + str(kw))
  plt.savefig(fileName)
  plt.close()


def plotFalseMatches(listOfNoise, errors, kw,
                fileName = "images/scalar_false_positives.pdf"):
  fig, ax = plt.subplots()

  fig.suptitle("Probability of false negatives with $k_w$=" + str(kw))
  ax.set_xlabel("Pct of components set to zero")
  ax.set_ylabel("Frequency of false negatives")
  # ax.set_yscale("log")

  ax.plot(listOfNoise, errors, 'k:', marker="o", color='black')

  plt.minorticks_off()
  plt.grid(True, alpha=0.3)

  plt.savefig(fileName)
  plt.close()



if __name__ == '__main__':

  # computeMatchProbabilities(kw=24, nTrials=1000)
  # computeMatchProbabilities(kw=16, nTrials=3000)
  # computeMatchProbabilities(kw=32, nTrials=3000)
  # computeMatchProbabilities(kw=48, nTrials=3000)
  # computeMatchProbabilities(kw=64, nTrials=3000)
  # computeMatchProbabilities(kw=96, nTrials=3000)

  # plotThetaDistribution(32)

  computeFalseNegativesParallel(kw=32, nTrials=10000)
  computeFalseNegativesParallel(kw=64, nTrials=10000)
  computeFalseNegativesParallel(kw=128, nTrials=10000)

  # computeScaledProbabilities(nTrials=6000)

  # TODO Compute false negatives