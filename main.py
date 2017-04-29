from scipy.misc import imread, imresize, imsave, fromimage, toimage
from scipy.optimize import fmin_l_bfgs_b
import numpy as np
import time
import argparse
import warnings

from keras.models import Model
from keras.layers import Input
from keras.layers.convolutional import Convolution2D, AveragePooling2D, MaxPooling2D
from keras import backend as K
from keras.utils.data_utils import get_file
from keras.utils.layer_utils import convert_all_kernels_in_model











input_tensor = [0,0,0]
shape = (0,0)

ip = Input(tensor=input_tensor, shape=shape)

# build the VGG16 network with our 3 images as input
x = Convolution2D(64, 3, 3, activation='relu', name='conv1_1', border_mode='same')(ip)
x = Convolution2D(64, 3, 3, activation='relu', name='conv1_2', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(128, 3, 3, activation='relu', name='conv2_1', border_mode='same')(x)
x = Convolution2D(128, 3, 3, activation='relu', name='conv2_2', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(256, 3, 3, activation='relu', name='conv3_1', border_mode='same')(x)
x = Convolution2D(256, 3, 3, activation='relu', name='conv3_2', border_mode='same')(x)
x = Convolution2D(256, 3, 3, activation='relu', name='conv3_3', border_mode='same')(x)
if args.model == "vgg19":
    x = Convolution2D(256, 3, 3, activation='relu', name='conv3_4', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(512, 3, 3, activation='relu', name='conv4_1', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv4_2', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv4_3', border_mode='same')(x)
if args.model == "vgg19":
    x = Convolution2D(512, 3, 3, activation='relu', name='conv4_4', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(512, 3, 3, activation='relu', name='conv5_1', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv5_2', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv5_3', border_mode='same')(x)
if args.model == "vgg19":
    x = Convolution2D(512, 3, 3, activation='relu', name='conv5_4', border_mode='same')(x)
x = pooling_func(x)

model = Model(ip, x)

if K.image_dim_ordering() == "th":
    if args.model == "vgg19":
        weights = get_file('vgg19_weights_th_dim_ordering_th_kernels_notop.h5', TH_19_WEIGHTS_PATH_NO_TOP, cache_subdir='models')
    else:
        weights = get_file('vgg16_weights_th_dim_ordering_th_kernels_notop.h5', THEANO_WEIGHTS_PATH_NO_TOP, cache_subdir='models')
else:
    if args.model == "vgg19":
        weights = get_file('vgg19_weights_tf_dim_ordering_tf_kernels_notop.h5', TF_19_WEIGHTS_PATH_NO_TOP, cache_subdir='models')
    else:
        weights = get_file('vgg16_weights_tf_dim_ordering_tf_kernels_notop.h5', TF_WEIGHTS_PATH_NO_TOP, cache_subdir='models')

model.load_weights(weights)

if K.backend() == 'tensorflow' and K.image_dim_ordering() == "th":
    warnings.warn('You are using the TensorFlow backend, yet you '
                  'are using the Theano '
                  'image dimension ordering convention '
                  '(`image_dim_ordering="th"`). '
                  'For best performance, set '
                  '`image_dim_ordering="tf"` in '
                  'your Keras config '
                  'at ~/.keras/keras.json.')
    convert_all_kernels_in_model(model)

print('Model loaded.')

# get the symbolic outputs of each "key" layer (we gave them unique names).
outputs_dict = dict([(layer.name, layer.output) for layer in model.layers])
shape_dict = dict([(layer.name, layer.output_shape) for layer in model.layers])

# compute the neural style loss
# first we need to define 4 util functions

# the gram matrix of an image tensor (feature-wise outer product)
def gram_matrix(x):
    assert K.ndim(x) == 3
    if K.image_dim_ordering() == "th":
        features = K.batch_flatten(x)
    else:
        features = K.batch_flatten(K.permute_dimensions(x, (2, 0, 1)))
    gram = K.dot(features, K.transpose(features))
    return gram


# the "style loss" is designed to maintain
# the style of the reference image in the generated image.
# It is based on the gram matrices (which capture style) of
# feature maps from the style reference image
# and from the generated image
def style_loss(style, combination, mask_path=None, nb_channels=None):
    assert K.ndim(style) == 3
    assert K.ndim(combination) == 3

    if mask_path is not None:
        style_mask = K.variable(load_mask(mask_path, nb_channels))

        style = style * K.stop_gradient(style_mask)
        combination = combination * K.stop_gradient(style_mask)

        del style_mask

    S = gram_matrix(style)
    C = gram_matrix(combination)
    channels = 3
    size = img_width * img_height
    return K.sum(K.square(S - C)) / (4. * (channels ** 2) * (size ** 2))


# an auxiliary loss function
# designed to maintain the "content" of the
# base image in the generated image
def content_loss(base, combination):
    channel_dim = 0 if K.image_dim_ordering() == "th" else -1

    channels = K.shape(base)[channel_dim]
    size = img_width * img_height

    if args.content_loss_type == 1:
        multiplier = 1 / (2. * channels ** 0.5 * size ** 0.5)
    elif args.content_loss_type == 2:
        multiplier = 1 / (channels * size)
    else:
        multiplier = 1.

    return multiplier * K.sum(K.square(combination - base))


# the 3rd loss function, total variation loss,
# designed to keep the generated image locally coherent
def total_variation_loss(x):
    assert K.ndim(x) == 4
    if K.image_dim_ordering() == 'th':
        a = K.square(x[:, :, :img_width - 1, :img_height - 1] - x[:, :, 1:, :img_height - 1])
        b = K.square(x[:, :, :img_width - 1, :img_height - 1] - x[:, :, :img_width - 1, 1:])
    else:
        a = K.square(x[:, :img_width - 1, :img_height - 1, :] - x[:, 1:, :img_height - 1, :])
        b = K.square(x[:, :img_width - 1, :img_height - 1, :] - x[:, :img_width - 1, 1:, :])
    return K.sum(K.pow(a + b, 1.25))


# combine these loss functions into a single scalar
loss = K.variable(0.)
layer_features = outputs_dict[args.content_layer]  # 'conv5_2' or 'conv4_2'
base_image_features = layer_features[0, :, :, :]
combination_features = layer_features[nb_tensors - 1, :, :, :]
loss += content_weight * content_loss(base_image_features,
                                      combination_features)

channel_index = 1 if K.image_dim_ordering() == "th" else -1

feature_layers = ['conv1_1', 'conv2_1', 'conv3_1', 'conv4_1', 'conv5_1']
for layer_name in feature_layers:
    layer_features = outputs_dict[layer_name]
    shape = shape_dict[layer_name]
    combination_features = layer_features[nb_tensors - 1, :, :, :]

    style_reference_features = layer_features[1:nb_tensors - 1, :, :, :]
    sl = []
    for j in range(nb_style_images):
        sl.append(style_loss(style_reference_features[j], combination_features, style_masks[j], shape))

    for j in range(nb_style_images):
        loss += (style_weights[j] / len(feature_layers)) * sl[j]

loss += total_variation_weight * total_variation_loss(combination_image)

# get the gradients of the generated image wrt the loss
grads = K.gradients(loss, combination_image)

outputs = [loss]
if type(grads) in {list, tuple}:
    outputs += grads
else:
    outputs.append(grads)

f_outputs = K.function([combination_image], outputs)


def eval_loss_and_grads(x):
    if K.image_dim_ordering() == 'th':
        x = x.reshape((1, 3, img_width, img_height))
    else:
        x = x.reshape((1, img_width, img_height, 3))
    outs = f_outputs([x])
    loss_value = outs[0]
    if len(outs[1:]) == 1:
        grad_values = outs[1].flatten().astype('float64')
    else:
        grad_values = np.array(outs[1:]).flatten().astype('float64')
    return loss_value, grad_values


# this Evaluator class makes it possible
# to compute loss and gradients in one pass
# while retrieving them via two separate functions,
# "loss" and "grads". This is done because scipy.optimize
# requires separate functions for loss and gradients,
# but computing them separately would be inefficient.
class Evaluator(object):
    def __init__(self):
        self.loss_value = None
        self.grads_values = None

    def loss(self, x):
        assert self.loss_value is None
        loss_value, grad_values = eval_loss_and_grads(x)
        self.loss_value = loss_value
        self.grad_values = grad_values
        return self.loss_value

    def grads(self, x):
        assert self.loss_value is not None
        grad_values = np.copy(self.grad_values)
        self.loss_value = None
        self.grad_values = None
        return grad_values


evaluator = Evaluator()

# run scipy-based optimization (L-BFGS) over the pixels of the generated image
# so as to minimize the neural style loss


if "content" in args.init_image or "gray" in args.init_image:
    x = preprocess_image(base_image_path, True, read_mode=read_mode)
elif "noise" in args.init_image:
    x = np.random.uniform(0, 255, (1, img_width, img_height, 3)) - 128.

    if K.image_dim_ordering() == "th":
        x = x.transpose((0, 3, 1, 2))
else:
    print("Using initial image : ", args.init_image)
    x = preprocess_image(args.init_image, read_mode=read_mode)

num_iter = args.num_iter
prev_min_val = -1

improvement_threshold = float(args.min_improvement)

for i in range(num_iter):
    print("Starting iteration %d of %d" % ((i + 1), num_iter))
    start_time = time.time()

    x, min_val, info = fmin_l_bfgs_b(evaluator.loss, x.flatten(), fprime=evaluator.grads, maxfun=20)

    if prev_min_val == -1:
        prev_min_val = min_val

    improvement = (prev_min_val - min_val) / prev_min_val * 100

    print('Current loss value:', min_val, " Improvement : %0.3f" % improvement, "%")
    prev_min_val = min_val
    # save current generated image
    img = deprocess_image(x.copy())

    if not rescale_image:
        img_ht = int(img_width * aspect_ratio)
        print("Rescaling Image to (%d, %d)" % (img_width, img_ht))
        img = imresize(img, (img_width, img_ht), interp=args.rescale_method)

    if rescale_image:
        print("Rescaling Image to (%d, %d)" % (img_WIDTH, img_HEIGHT))
        img = imresize(img, (img_WIDTH, img_HEIGHT), interp=args.rescale_method)

    fname = result_prefix + '_at_iteration_%d.png' % (i + 1)
    imsave(fname, img)
    end_time = time.time()
    print('Image saved as', fname)
    print('Iteration %d completed in %ds' % (i + 1, end_time - start_time))

    if improvement_threshold is not 0.0:
        if improvement < improvement_threshold and improvement is not 0.0:
            print("Improvement (%f) is less than improvement threshold (%f). Early stopping script." % (
                improvement, improvement_threshold))
            exit()