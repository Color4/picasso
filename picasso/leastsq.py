from scipy import optimize
from scipy.special import erf
import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import numba
import multiprocessing


@numba.jit(nopython=True, nogil=True)
def gaussian(mu, sigma, grid):
    norm = 0.3989422804014327 / sigma
    return norm * np.exp(-0.5 * ((grid - mu) / sigma)**2)


'''
def integrated_gaussian(mu, sigma, grid):
    norm = 0.70710678118654757 / sigma   # sq_norm = sqrt(0.5/sigma**2)
    return 0.5 * (erf((grid - mu + 0.5) * norm) - erf((grid - mu - 0.5) * norm))
'''


@numba.jit(nopython=True, nogil=True)
def outer(a, b, size, model, n, bg):
    for i in range(size):
        for j in range(size):
            model[i, j] = n * a[i] * b[j] + bg


@numba.jit(nopython=True, nogil=True)
def compute_model(theta, grid, size, model_x, model_y, model):
    model_x[:] = gaussian(theta[0], theta[4], grid)    # sx and sy are wrong with integrated gaussian
    model_y[:] = gaussian(theta[1], theta[5], grid)
    outer(model_y, model_x, size, model, theta[2], theta[3])
    return model


@numba.jit(nopython=True, nogil=True)
def compute_residuals(theta, spot, grid, size, model_x, model_y, model, residuals):
    compute_model(theta, grid, size, model_x, model_y, model)
    residuals[:, :] = spot - model
    return residuals.flatten()


def fit_spots(spots):
    theta = np.empty((len(spots), 6), dtype=np.float32)
    theta.fill(np.nan)
    size = spots.shape[1]
    size_half = int(size / 2)
    grid = np.arange(-size_half, size_half + 1, dtype=np.float32)
    model_x = np.empty(size, dtype=np.float32)
    model_y = np.empty(size, dtype=np.float32)
    model = np.empty((size, size), dtype=np.float32)
    residuals = np.empty((size, size), dtype=np.float32)
    print('worker starts fitting')
    # for i, spot in enumerate(tqdm(spots)):
    for i, spot in enumerate(spots):
        # theta is [x, y, photons, bg, sx, sy]
        theta0 = np.array([0, 0, np.sum(spot-spot.min()), spot.min(), 1, 1], dtype=np.float32)  # make it smarter
        args = (spot, grid, size, model_x, model_y, model, residuals)
        result = optimize.leastsq(compute_residuals, theta0, args=args, ftol=1e-2, xtol=1e-2)   # leastsq is much faster than least_squares
        theta[i] = result[0]
        '''
        model = compute_model(result[0], grid, size, model_x, model_y, model)
        plt.figure()
        plt.subplot(121)
        plt.imshow(spot, interpolation='none')
        plt.subplot(122)
        plt.imshow(model, interpolation='none')
        plt.colorbar()
        plt.show()
        '''
    return theta


def fit_spots_parallel(spots):
    import time
    n_workers = int(0.75 * multiprocessing.cpu_count())
    n_spots = len(spots)
    spots_per_worker = int(n_spots / _n_workers) + 1
    results = []
    pool = multiprocessing.Pool(n_workers)
    t0 = time.time()
    for i in range(0, n_spots, spots_per_worker):
        print('Starting worker', i)
        results.append(_pool.apply_async(fit_spots, (spots[i:i+spots_per_worker],)))
    t1 = time.time()
    pool.close()
    t0 = time.time()
    for result in results:
        result.wait()
    t1 = time.time()
    print('Fit time: {:.10f} seconds'.format(t1-t0))
    theta = [_.get() for _ in results]
    return np.vstack(theta)


def locs_from_fits(identifications, theta, box):
    box_offset = int(box/2)
    x = theta[:, 0] + identifications.x - box_offset
    y = theta[:, 1] + identifications.y - box_offset
    lpy = theta[:, 4] / np.sqrt(theta[:, 2])
    lpx = theta[:, 5] / np.sqrt(theta[:, 2])
    locs = np.rec.array((identifications.frame, x, y,
                         theta[:, 2], theta[:, 4], theta[:, 5],
                         theta[:, 3], lpx, lpy,
                         identifications.net_gradient),
                        dtype=[('frame', 'u4'), ('x', 'f4'), ('y', 'f4'),
                               ('photons', 'f4'), ('sx', 'f4'), ('sy', 'f4'),
                               ('bg', 'f4'), ('lpx', 'f4'), ('lpy', 'f4'),
                               ('net_gradient', 'f4')])
    locs.sort(kind='mergesort', order='frame')
    return locs
