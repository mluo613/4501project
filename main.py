from scipy.misc import imread, imresize, imsave, fromimage, toimage
from scipy.optimize import fmin_l_bfgs_b
import scipy.interpolate
import scipy.ndimage
import numpy as np
import time
import argparse
import warnings
from sklearn.feature_extraction.image import reconstruct_from_patches_2d, extract_patches_2d

from keras.models import Model
from keras.layers import Input
from keras.layers.convolutional import Convolution2D, AveragePooling2D, MaxPooling2D
from keras import backend as K
from keras.utils.data_utils import get_file
from keras.utils.layer_utils import convert_all_kernels_in_model

TF_WEIGHTS_PATH_NO_TOP = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.1/vgg16_weights_tf_dim_ordering_tf_kernels_notop.h5'

parser = argparse.ArgumentParser(description='Neural style transfer with Keras.')
parser.add_argument('base_image_path', metavar='base', type=str,
                    help='Path to the image to transform.')

parser.add_argument('style_image_paths', metavar='ref', nargs='+', type=str,
                    help='Path to the style reference image.')

parser.add_argument('result_prefix', metavar='res_prefix', type=str,
                    help='Prefix for the saved results.')

parser.add_argument("--image_size", dest="img_size", default=400, type=int,
                    help='Minimum image size')

parser.add_argument("--content_weight", dest="content_weight", default=0.025, type=float,
                    help="Weight of content")

parser.add_argument("--style_weight", dest="style_weight", nargs='+', default=[1], type=float,
                    help="Weight of style, can be multiple for multiple styles")

parser.add_argument("--total_variation_weight", dest="tv_weight", default=8.5e-5, type=float,
                    help="Total Variation weight")

parser.add_argument("--style_scale", dest="style_scale", default=1.0, type=float,
                    help="Scale the weighing of the style")

parser.add_argument("--num_iter", dest="num_iter", default=10, type=int,
                    help="Number of iterations")

parser.add_argument("--content_loss_type", default=0, type=int,
                    help='Can be one of 0, 1 or 2. Readme contains the required information of each mode.')

parser.add_argument("--content_layer", dest="content_layer", default="conv5_2", type=str,
                    help="Content layer used for content loss.")

parser.add_argument("--init_image", dest="init_image", default="content", type=str,
                    help="Initial image used to generate the final image. Options are 'content', 'noise', or 'gray'")




args = parser.parse_args()
base_image_path = args.base_image_path
style_reference_image_paths = args.style_image_paths
style_image_paths = [path for path in args.style_image_paths]
result_prefix = args.result_prefix
content_weight = args.content_weight
total_variation_weight = args.tv_weight

img_width = img_height = 0

img_WIDTH = img_HEIGHT = 0
aspect_ratio = 0

read_mode = "color"
style_weights = []
if len(style_image_paths) != len(args.style_weight):
    weight_sum = sum(args.style_weight) * args.style_scale
    count = len(style_image_paths)

    for i in range(len(style_image_paths)):
        style_weights.append(weight_sum / count)
else:
    style_weights = [weight*args.style_scale for weight in args.style_weight]

def pooling_func(x):
    # return AveragePooling2D((2, 2), strides=(2, 2))(x)
    return MaxPooling2D((2, 2), strides=(2, 2))(x)

#start proc_img

def preprocess_image(image_path, load_dims=False):
    global img_width, img_height, img_WIDTH, img_HEIGHT, aspect_ratio

    mode = "RGB"
    # mode = "RGB" if read_mode == "color" else "L"
    img = imread(image_path, mode=mode)  # Prevents crashes due to PNG images (ARGB)

    if load_dims:
        img_WIDTH = img.shape[0]
        img_HEIGHT = img.shape[1]
        aspect_ratio = float(img_HEIGHT) / img_WIDTH

        img_width = args.img_size
        img_height = int(img_width * aspect_ratio)

    img = imresize(img, (img_width, img_height)).astype('float32')

    # RGB -> BGR
    img = img[:, :, ::-1]

    img[:, :, 0] -= 103.939
    img[:, :, 1] -= 116.779
    img[:, :, 2] -= 123.68


    img = np.expand_dims(img, axis=0)
    return img


# util function to convert a tensor into a valid image
def deprocess_image(x):
    x = x.reshape((img_width, img_height, 3))

    x[:, :, 0] += 103.939
    x[:, :, 1] += 116.779
    x[:, :, 2] += 123.68

    # BGR -> RGB
    x = x[:, :, ::-1]

    x = np.clip(x, 0, 255).astype('uint8')
    return x



base_image = K.variable(preprocess_image(base_image_path, True))

style_reference_images = [K.variable(preprocess_image(path)) for path in style_image_paths]

# this will contain our generated image
combination_image = K.placeholder((1, img_width, img_height, 3)) # tensorflow

image_tensors = [base_image]
for style_image_tensor in style_reference_images:
    image_tensors.append(style_image_tensor)
image_tensors.append(combination_image)

nb_tensors = len(image_tensors)
nb_style_images = nb_tensors - 2 # Content and Output image not considered

# combine the various images into a single Keras tensor
input_tensor = K.concatenate(image_tensors, axis=0)

shape = (nb_tensors, img_width, img_height, 3) #tensorflow


#build the model
model_input = Input(tensor=input_tensor, shape=shape)

# build the VGG16 network with our 3 images as input
x = Convolution2D(64, 3, 3, activation='relu', name='conv1_1', border_mode='same')(model_input)
x = Convolution2D(64, 3, 3, activation='relu', name='conv1_2', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(128, 3, 3, activation='relu', name='conv2_1', border_mode='same')(x)
x = Convolution2D(128, 3, 3, activation='relu', name='conv2_2', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(256, 3, 3, activation='relu', name='conv3_1', border_mode='same')(x)
x = Convolution2D(256, 3, 3, activation='relu', name='conv3_2', border_mode='same')(x)
x = Convolution2D(256, 3, 3, activation='relu', name='conv3_3', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(512, 3, 3, activation='relu', name='conv4_1', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv4_2', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv4_3', border_mode='same')(x)
x = pooling_func(x)

x = Convolution2D(512, 3, 3, activation='relu', name='conv5_1', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv5_2', border_mode='same')(x)
x = Convolution2D(512, 3, 3, activation='relu', name='conv5_3', border_mode='same')(x)
x = pooling_func(x)

model = Model(model_input, x)

weights = get_file('vgg16_weights_tf_dim_ordering_tf_kernels_notop.h5', TF_WEIGHTS_PATH_NO_TOP, cache_subdir='models')

print("Weights Path: ", weights)

model.load_weights(weights)

print('Model loaded.')

# get the symbolic outputs of each "key" layer (we gave them unique names).
outputs_dict = dict([(layer.name, layer.output) for layer in model.layers])
shape_dict = dict([(layer.name, layer.output_shape) for layer in model.layers])


def make_patches(x, patch_size, patch_stride):
    '''Break image `x` up into a bunch of patches.'''
    from theano.tensor.nnet.neighbours import images2neibs
    x = K.expand_dims(x, 0)
    patches = images2neibs(x,
        (patch_size, patch_size), (patch_stride, patch_stride),
        mode='valid')
    # neibs are sorted per-channel
    patches = K.reshape(patches, (K.shape(x)[1], K.shape(patches)[0] // K.shape(x)[1], patch_size, patch_size))
    patches = K.permute_dimensions(patches, (1, 0, 2, 3))
    patches_norm = K.sqrt(K.sum(K.square(patches), axis=(1,2,3), keepdims=True))
    return patches, patches_norm


def find_patch_matches(a, a_norm, b):
    '''For each patch in A, find the best matching patch in B'''
    # we want cross-correlation here so flip the kernels
    convs = K.conv2d(a, b[:, :, ::-1, ::-1], border_mode='valid')
    argmax = K.argmax(convs / a_norm, axis=1)
    return argmax

# compute the neural style loss
# first we need to define 4 util functions

# the gram matrix of an image tensor (feature-wise outer product)
def gram_matrix(x):
    features = K.batch_flatten(K.permute_dimensions(x, (2, 0, 1)))
    gram = K.dot(features, K.transpose(features))
    return gram


# the "style loss" is designed to maintain
# the style of the reference image in the generated image.
# It is based on the gram matrices (which capture style) of
# feature maps from the style reference image
# and from the generated image
def style_loss(style, combination):
    style_gram = gram_matrix(style)
    combo_gram = gram_matrix(combination)
    channels = 3
    size = img_width * img_height
    return K.sum(K.square(style_gram - combo_gram)) / (4. * (channels ** 2) * (size ** 2))


# an auxiliary loss function
# designed to maintain the "content" of the
# base image in the generated image
def content_loss(base, combination):
    channels = K.shape(base)[-1]
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

channel_index = -1

#Style Loss calculation
feature_layers = ['conv1_1', 'conv2_1', 'conv3_1', 'conv4_1', 'conv5_1']
for layer_name in feature_layers:
    output_features = outputs_dict[layer_name]
    shape = shape_dict[layer_name]
    combination_features = output_features[nb_tensors - 1, :, :, :]

    style_features = output_features[1:nb_tensors - 1, :, :, :]
    sl = []
    for j in range(nb_style_images):
        sl.append(style_loss(style_features[j], combination_features))

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
    x = x.reshape((1, img_width, img_height, 3))
    outs = f_outputs([x])
    loss_value = outs[0]
    if len(outs[1:]) == 1:
        grad_values = outs[1].flatten().astype('float64')
    else:
        grad_values = np.array(outs[1:]).flatten().astype('float64')
    return loss_value, grad_values


# # this Evaluator class makes it possible
# # to compute loss and gradients in one pass
# # while retrieving them via two separate functions,
# # "loss" and "grads". This is done because scipy.optimize
# # requires separate functions for loss and gradients,
# # but computing them separately would be inefficient.
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
    x = preprocess_image(base_image_path, True)
elif "noise" in args.init_image:
    x = np.random.uniform(0, 255, (1, img_width, img_height, 3)) - 128.

    if K.image_dim_ordering() == "th":
        x = x.transpose((0, 3, 1, 2))
else:
    print("Using initial image : ", args.init_image)
    x = preprocess_image(args.init_image)

num_iter = args.num_iter
prev_min_val = -1


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

    img_ht = int(img_width * aspect_ratio)
    print("Rescaling Image to (%d, %d)" % (img_width, img_ht))
    img = imresize(img, (img_width, img_ht), interp="bilinear")

    fname = result_prefix + '_at_iteration_%d.png' % (i + 1)
    imsave(fname, img)
    end_time = time.time()
    print('Image saved as', fname)
    print('Iteration %d completed in %ds' % (i + 1, end_time - start_time))
