"""
Deterministic unsupervised adversarial autoencoder.

 We are using:
    - Gaussian distribution as prior distribution.
    - Convolutional layers.
    - Discriminator in x space
"""
import time
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import gridspec
import matplotlib.patches as mpatches
import numpy as np
import tensorflow as tf


PROJECT_ROOT = Path.cwd()

# -------------------------------------------------------------------------------------------------------------
# Set random seed
random_seed = 42
tf.random.set_seed(random_seed)
np.random.seed(random_seed)

# -------------------------------------------------------------------------------------------------------------
output_dir = PROJECT_ROOT / 'outputs'
output_dir.mkdir(exist_ok=True)

experiment_dir = output_dir / 'unsupervised_aae_deterministic_w_discriminator'
experiment_dir.mkdir(exist_ok=True)

latent_space_dir = experiment_dir / 'latent_space'
latent_space_dir.mkdir(exist_ok=True)

reconstruction_dir = experiment_dir / 'reconstruction'
reconstruction_dir.mkdir(exist_ok=True)

sampling_dir = experiment_dir / 'sampling'
sampling_dir.mkdir(exist_ok=True)

# -------------------------------------------------------------------------------------------------------------
# Loading data
print("Loading data...")
(x_train, y_train), (x_test, y_test) = tf.keras.datasets.mnist.load_data()

x_train = x_train.astype('float32') / 255.
x_test = x_test.astype('float32') / 255.

x_train = x_train.reshape(x_train.shape[0], 28, 28, 1)
x_test = x_test.reshape(x_test.shape[0], 28, 28, 1)

# -------------------------------------------------------------------------------------------------------------
# Create the dataset iterator
batch_size = 256
train_buf = 60000

train_dataset = tf.data.Dataset.from_tensor_slices(x_train)
train_dataset = train_dataset.shuffle(buffer_size=train_buf)
train_dataset = train_dataset.batch(batch_size)


# -------------------------------------------------------------------------------------------------------------
# Create models
def make_encoder_model(z_size):
    inputs = tf.keras.layers.Input(shape=(28, 28, 1))

    x = tf.keras.layers.Conv2D(filters=32, kernel_size=3, strides=2, padding='same')(inputs)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Conv2D(filters=64, kernel_size=3, strides=2, padding='same')(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Conv2D(filters=64, kernel_size=3, strides=2, padding='same')(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Conv2D(filters=128, kernel_size=3, strides=2, padding='same')(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    z = tf.keras.layers.Conv2D(filters=z_size, kernel_size=3, strides=2, padding='same')(x)

    model = tf.keras.Model(inputs=inputs, outputs=z)
    return model


def make_decoder_model(z_size):
    encoded = tf.keras.Input(shape=(1, 1, z_size))

    x = tf.keras.layers.Conv2D(64, kernel_size=3, padding='same', activation='relu')(encoded)
    x = tf.keras.layers.UpSampling2D((2, 2))(x)
    x = tf.keras.layers.Conv2D(64, kernel_size=3, padding='same', activation='relu')(x)
    x = tf.keras.layers.UpSampling2D((2, 2))(x)
    x = tf.keras.layers.Conv2D(64, kernel_size=3, padding='same', activation='relu')(x)
    x = tf.keras.layers.UpSampling2D((2, 2))(x)
    x = tf.keras.layers.Conv2D(64, kernel_size=3, padding='same', activation='relu')(x)
    x = tf.keras.layers.UpSampling2D((2, 2))(x)
    x = tf.keras.layers.Conv2D(64, kernel_size=3, activation='relu')(x)
    x = tf.keras.layers.UpSampling2D((2, 2))(x)

    reconstruction = tf.keras.layers.Conv2D(filters=1, kernel_size=3, activation='sigmoid', padding='same')(x)
    decoder = tf.keras.Model(inputs=encoded, outputs=reconstruction)
    return decoder



def make_discriminator_z_model(z_size):
    encoded = tf.keras.Input(shape=(z_size,))
    x = tf.keras.layers.Dense(128)(encoded)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Dense(128)(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    prediction = tf.keras.layers.Dense(1)(x)
    model = tf.keras.Model(inputs=encoded, outputs=prediction)
    return model


def make_discriminator_x_model():
    inputs = tf.keras.layers.Input(shape=(28, 28, 1))

    x = tf.keras.layers.Conv2D(filters=16, kernel_size=4, strides=2, padding='same')(inputs)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Conv2D(filters=32, kernel_size=4, strides=2, padding='same')(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    x = tf.keras.layers.Conv2D(filters=64, kernel_size=4, strides=2, padding='same')(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.LeakyReLU(0.2)(x)
    z = tf.keras.layers.Conv2D(filters=1, kernel_size=4, strides=1, padding='valid')(x)

    model = tf.keras.Model(inputs=inputs, outputs=z)
    return model



z_dim = 2
encoder = make_encoder_model(z_dim)
decoder = make_decoder_model(z_dim)
discriminator_z = make_discriminator_z_model(z_dim)
discriminator_x = make_discriminator_x_model()


# -------------------------------------------------------------------------------------------------------------
# Define loss functions
ae_loss_weight = 1.
gen_loss_weight = 1.
dc_loss_weight = 1.

cross_entropy = tf.keras.losses.BinaryCrossentropy(from_logits=True)
mse = tf.keras.losses.MeanSquaredError()
accuracy = tf.keras.metrics.BinaryAccuracy()


def autoencoder_loss(inputs, reconstruction, loss_weight):
    return loss_weight * mse(inputs, reconstruction)


def discriminator_loss(real_output, fake_output, loss_weight):
    loss_real = cross_entropy(tf.ones_like(real_output), real_output)
    loss_fake = cross_entropy(tf.zeros_like(fake_output), fake_output)
    return loss_weight * (loss_fake + loss_real)


def generator_loss(fake_output, loss_weight):
    return loss_weight * cross_entropy(tf.ones_like(fake_output), fake_output)


# -------------------------------------------------------------------------------------------------------------
# Define optimizers
learning_rate = 0.0001

ae_optimizer = tf.keras.optimizers.Adam(lr=learning_rate)
dc_z_optimizer = tf.keras.optimizers.Adam(lr=learning_rate)
gen_z_optimizer = tf.keras.optimizers.Adam(lr=learning_rate)
dc_x_optimizer = tf.keras.optimizers.Adam(lr=learning_rate)
gen_x_optimizer = tf.keras.optimizers.Adam(lr=learning_rate)


@tf.function
def train_step(batch_x):
    # -------------------------------------------------------------------------------------------------------------
    # Autoencoder
    with tf.GradientTape() as ae_tape:
        encoder_output = encoder(batch_x, training=True)
        decoder_output = decoder(encoder_output, training=True)

        # Autoencoder loss
        ae_loss = autoencoder_loss(batch_x, decoder_output, ae_loss_weight)

    ae_grads = ae_tape.gradient(ae_loss, encoder.trainable_variables + decoder.trainable_variables)
    ae_optimizer.apply_gradients(zip(ae_grads, encoder.trainable_variables + decoder.trainable_variables))


    # -------------------------------------------------------------------------------------------------------------
    # Discriminator Z
    with tf.GradientTape() as dc_tape:
        real_distribution = tf.random.normal([batch_size, 1, 1, z_dim], mean=0.0, stddev=1.0)
        encoder_output = encoder(batch_x, training=True)

        dc_z_real = discriminator_z(real_distribution, training=True)
        dc_z_fake = discriminator_z(encoder_output, training=True)

        # Discriminator Loss
        dc_z_loss = discriminator_loss(dc_z_real, dc_z_fake, dc_loss_weight)

        # Discriminator Acc
        dc_z_acc = accuracy(tf.concat([tf.ones_like(dc_z_real), tf.zeros_like(dc_z_fake)], axis=0),
                          tf.concat([dc_z_real, dc_z_fake], axis=0))

    dc_grads = dc_tape.gradient(dc_z_loss, discriminator_z.trainable_variables)
    # dc_z_optimizer.apply_gradients(zip(dc_grads, discriminator_z.trainable_variables))

    # -------------------------------------------------------------------------------------------------------------
    # Generator Z (Encoder)
    with tf.GradientTape() as gen_tape:
        encoder_output = encoder(batch_x, training=True)
        dc_z_fake = discriminator_z(encoder_output, training=True)

        # Generator loss
        gen_z_loss = generator_loss(dc_z_fake, gen_loss_weight)

    gen_z_grads = gen_tape.gradient(gen_z_loss, encoder.trainable_variables)
    # gen_z_optimizer.apply_gradients(zip(gen_z_grads, encoder.trainable_variables))

    # -------------------------------------------------------------------------------------------------------------
    # Discriminator X
    with tf.GradientTape() as dc_x_tape:
        encoder_output = encoder(batch_x, training=True)
        decoder_output = decoder(encoder_output, training=True)

        d_x_real = discriminator_x(batch_x, training=True)
        d_x_fake = discriminator_x(decoder_output, training=True)

        # Discriminator X Loss
        dc_x_loss = discriminator_loss(d_x_real, d_x_fake, dc_loss_weight)

        # Discriminator X Acc
        dc_z_acc = accuracy(tf.concat([tf.ones_like(d_x_real), tf.zeros_like(d_x_fake)], axis=0),
                          tf.concat([d_x_real, d_x_fake], axis=0))

    dc_x_grads = dc_x_tape.gradient(dc_x_loss, discriminator_x.trainable_variables)
    # dc_x_optimizer.apply_gradients(zip(dc_x_grads, discriminator_x.trainable_variables))

    # -------------------------------------------------------------------------------------------------------------
    # Generator X (Decoder)
    with tf.GradientTape() as gen_x_tape:
        encoder_output = encoder(batch_x, training=True)
        decoder_output = decoder(encoder_output, training=True)

        # Generator X loss
        d_x_fake = discriminator_x(decoder_output, training=True)

        gen_x_loss = generator_loss(d_x_fake, gen_loss_weight)

    gen_x_grads = gen_x_tape.gradient(gen_x_loss, decoder.trainable_variables)
    # gen_x_optimizer.apply_gradients(zip(gen_x_grads, decoder.trainable_variables))

    return ae_loss, dc_z_loss, dc_z_acc, gen_z_loss, dc_x_loss, dc_x_acc, gen_x_loss


# -------------------------------------------------------------------------------------------------------------
# Training loop
n_epochs = 200
for epoch in range(n_epochs):
    start = time.time()

    epoch_ae_loss_avg = tf.metrics.Mean()
    epoch_dc_z_loss_avg = tf.metrics.Mean()
    epoch_dc_z_acc_avg = tf.metrics.Mean()
    epoch_gen_z_loss_avg = tf.metrics.Mean()
    epoch_dc_x_loss_avg = tf.metrics.Mean()
    epoch_dc_x_acc_avg = tf.metrics.Mean()
    epoch_gen_x_loss_avg = tf.metrics.Mean()

    for batch, (batch_x) in enumerate(train_dataset):
        ae_loss, dc_z_loss, dc_z_acc, gen_z_loss, dc_x_loss, dc_x_acc, gen_x_loss = train_step(batch_x)

        epoch_ae_loss_avg(ae_loss)
        epoch_dc_z_loss_avg(dc_z_loss)
        epoch_dc_z_acc_avg(dc_z_acc)
        epoch_gen_z_loss_avg(gen_z_loss)
        epoch_dc_x_loss_avg(dc_x_loss)
        epoch_dc_x_acc_avg(dc_x_acc)
        epoch_gen_x_loss_avg(gen_x_loss)


    epoch_time = time.time() - start
    print(
        '{:4d}: TIME: {:.2f} ETA: {:.2f} AE_LOSS: {:.4f} DC_Z_LOSS: {:.4f} DC_Z_ACC: {:.4f} GEN_Z_LOSS: {:.4f} DC_X_LOSS: {:.4f} DC_X_ACC: {:.4f} GEN_X_LOSS: {:.4f}'
        .format(epoch, epoch_time,
                epoch_time * (n_epochs - epoch),
                epoch_ae_loss_avg.result(),
                epoch_dc_z_loss_avg.result(),
                epoch_dc_z_acc_avg.result(),
                epoch_gen_z_loss_avg.result(),
                epoch_dc_x_loss_avg.result(),
                epoch_dc_x_acc_avg.result(),
                epoch_gen_x_loss_avg.result()))


    # -------------------------------------------------------------------------------------------------------------
    if epoch % 10 == 0:
        # Latent Space
        x_test_encoded = encoder(x_test, training=False)
        label_list = list(y_test)

        fig = plt.figure()
        classes = set(label_list)
        colormap = plt.cm.rainbow(np.linspace(0, 1, len(classes)))
        kwargs = {'alpha': 0.8, 'c': [colormap[i] for i in label_list]}
        ax = plt.subplot(111, aspect='equal')
        box = ax.get_position()
        ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
        handles = [mpatches.Circle((0, 0), label=class_, color=colormap[i])
                   for i, class_ in enumerate(classes)]
        ax.legend(handles=handles, shadow=True, bbox_to_anchor=(1.05, 0.45),
                  fancybox=True, loc='center left')
        plt.scatter(x_test_encoded[:, :, :, 0], x_test_encoded[:, :, :, 1], s=2, **kwargs)
        ax.set_xlim([-3, 3])
        ax.set_ylim([-3, 3])

        plt.savefig(latent_space_dir / ('epoch_%d.png' % epoch))
        plt.close('all')

        # Reconstruction
        n_digits = 20  # how many digits we will display
        x_test_decoded = decoder(encoder(x_test[:n_digits], training=False), training=False)
        x_test_decoded = np.reshape(x_test_decoded, [-1, 28, 28]) * 255
        fig = plt.figure(figsize=(20, 4))
        for i in range(n_digits):
            # display original
            ax = plt.subplot(2, n_digits, i + 1)
            plt.imshow(x_test[i].reshape(28, 28))
            plt.gray()
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

            # display reconstruction
            ax = plt.subplot(2, n_digits, i + 1 + n_digits)
            plt.imshow(x_test_decoded[i])
            plt.gray()
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

        plt.savefig(reconstruction_dir / ('epoch_%d.png' % epoch))
        plt.close('all')

        # Sampling
        x_points = np.linspace(-3, 3, 20).astype(np.float32)
        y_points = np.linspace(-3, 3, 20).astype(np.float32)

        nx, ny = len(x_points), len(y_points)
        plt.subplot()
        gs = gridspec.GridSpec(nx, ny, hspace=0.05, wspace=0.05)

        for i, g in enumerate(gs):
            z = np.concatenate(([x_points[int(i / ny)]], [y_points[int(i % nx)]]))
            z = np.reshape(z, (1, 1, 1, 2))
            x = decoder(z, training=False).numpy()
            ax = plt.subplot(g)
            img = np.array(x.tolist()).reshape(28, 28)
            ax.imshow(img, cmap='gray')
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect('auto')
        plt.savefig(sampling_dir / ('epoch_%d.png' % epoch))
        plt.close('all')