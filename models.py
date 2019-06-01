import tensorflow as tf
from tensorflow.keras import layers
import numpy as np


class ConvDiscriminator(tf.keras.Model):
    def __init__(self, num_feats, num_labels):
        super(ConvDiscriminator, self).__init__()
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.emb_layer = layers.Embedding(self.num_labels, 32)
        self.conv1 = layers.Conv1D(32, kernel_size=(
            3), strides=(3), padding='same', activation='relu')
        self.conv2 = layers.Conv1D(32, kernel_size=(
            3), strides=(3), padding='same', activation='relu')
        self.conv2 = layers.Conv1D(32, kernel_size=(
            3), strides=(3), padding='same', activation='relu')
        self.fc_out = layers.Dense(2)

    def __call__(self, x, y):
        batch_size, time_len, _ = x.shape
        label_emb = self.emb_layer(y)
        out = self.conv1(x)
        out = self.conv2(out)
        out = self.conv2(out)
        out = tf.reshape(out, [batch_size, -1])
        out = tf.concat([out, label_emb], axis=-1)
        out = self.fc_out(out)
        return out


class RNNDiscriminator(tf.keras.Model):
    def __init__(self, num_feats, num_labels, num_units=32):
        super(RNNDiscriminator, self).__init__()
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.num_units = num_units

        self.emb_layer = layers.Embedding(self.num_labels, 32)
        self.lstm = layers.CuDNNGRU(
            self.num_units, return_sequences=True, return_state=True)
        self.fc_out = layers.Dense(2)

    def __call__(self, x, y):
        label_emb = self.emb_layer(y)
        out, last_h = self.lstm(x)
        last_out = out[:, -1, :]
        out = tf.concat([last_out, label_emb], axis=-1)
        out = self.fc_out(out)
        return out


class HARLSTMModel(tf.keras.Model):
    def __init__(self, num_feats, num_labels, num_units=64):
        super(HARLSTMModel, self).__init__()
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.num_units = num_units
        self.lstm = layers.CuDNNGRU(
            self.num_units, return_sequences=True, return_state=True)
        self.lstm2 = layers.CuDNNGRU(
            self.num_units, return_sequences=True, return_state=True)
        self.lstm3 = layers.CuDNNGRU(
            self.num_units, return_sequences=True, return_state=True)
        self.fc = layers.Dense(self.num_labels, activation=None)

    def __call__(self, x):
        out, last_h = self.lstm(x)
        out, last_h = self.lstm2(out)
        out, last_h = self.lstm3(out)
        out = self.fc(out[:, -1, :])
        return out


class CRNNModel(tf.keras.Model):

    def __init__(self, num_feats, num_labels, num_units=64):
        super(CRNNModel, self).__init__()
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.num_units = num_units
        self.num_layers = 3
        self.fc = layers.Dense(32)
        self.emb = layers.Embedding(self.num_labels, 32)
        self.gru = layers.CuDNNGRU(
            self.num_units, return_state=True, return_sequences=True)
        self.gru2 = layers.CuDNNGRU(
            self.num_units, return_state=True, return_sequences=True)
        self.gru3 = layers.CuDNNGRU(
            self.num_units, return_state=True, return_sequences=True)

        self.fc_last = layers.Dense(self.num_feats)

    def __call__(self, x, y, hidden):
        batch_size, time_len, feats = x.shape
        h1 = self.fc(x)
        h2 = self.emb(y)
        h2 = tf.tile(tf.expand_dims(h2, 1), [1, time_len, 1])
        h = tf.concat([h1, h2], axis=-1)
        outputs, last_state1 = self.gru(h, hidden[0])
        outputs, last_state2 = self.gru2(outputs, hidden[1])
        outputs, last_state3 = self.gru3(outputs, hidden[2])
        preds = self.fc_last(outputs)
        return preds, [last_state1, last_state2, last_state3]

    def sample(self, labels, z, max_len=128):
        """ generates samples conditioned on the given label """
        num_examples = labels.shape[0]
        # TODO(malzantot): fix the init pred : probably add an START token
        step_pred = tf.convert_to_tensor(
            np.random.normal(scale=1.0, size=(num_examples, 1, self.num_feats)).astype(np.float32))
        preds = []
        last_state = z  # use z as last state
        for _ in range(max_len):
            step_pred, last_state = self(step_pred, labels, last_state)
            preds.append(step_pred)
        output = tf.concat(preds, axis=1)
        return output


class RNNEncoder(tf.keras.Model):
    def __init__(self, rnn_units=64, z_dim=64):
        super(RNNEncoder, self).__init__()
        self.rnn_units = rnn_units
        self.z_dim = z_dim
        self.gru = layers.CuDNNGRU(
            self.rnn_units, return_state=True, return_sequences=True)
        self.fc_mu = layers.Dense(self.z_dim)
        self.fc_logvar = layers.Dense(self.z_dim)

    def reparmeterize(self, mu, sigma):
        eps = tf.random_normal(tf.shape(sigma))
        return tf.multiply(eps, sigma) + mu

    def __call__(self, x, hidden=None):
        batch_size, time_len, feat_size = x.shape
        if hidden is None:
            hidden = tf.zeros([batch_size, self.rnn_units])
        outputs, last_hidden = self.gru(x, hidden)
        mu = self.fc_mu(last_hidden)
        log_var = self.fc_logvar(last_hidden)
        sigma = tf.exp(log_var/2)
        z = self.reparmeterize(mu, sigma)
        return z, mu, log_var


class RNNDecoder(tf.keras.Model):
    def __init__(self, rnn_units=64, num_feats=6, num_labels=6):
        super(RNNDecoder, self).__init__()
        self.rnn_units = rnn_units
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.gru1 = layers.CuDNNGRU(
            self.rnn_units, return_state=True, return_sequences=True)
        self.gru2 = layers.CuDNNGRU(
            self.rnn_units, return_state=True, return_sequences=True)
        self.gru3 = layers.CuDNNGRU(
            self.rnn_units, return_state=True, return_sequences=True)
        self.fc_out = layers.Dense(self.num_feats)
        self.label_emb = layers.Embedding(self.num_labels, 6)

    def __call__(self, x, hidden, y):
        batch_size, time_len, feat_dim = x.shape
        y_emb = self.label_emb(y)
        y_emb = tf.tile(tf.expand_dims(y_emb, axis=1), [1, time_len, 1])

        rnn_input = tf.concat([x, y_emb], axis=-1)
        output1, last_state1 = self.gru1(rnn_input, hidden[0])
        output2, last_state2 = self.gru2(output1, hidden[1])
        output3, last_state3 = self.gru3(output2, hidden[2])

        output = self.fc_out(output3)
        new_hidden = [last_state1, last_state2, last_state3]
        return output, new_hidden


class RVAEModel(tf.keras.Model):

    def __init__(self, enc_rnn_units=64, z_dim=64, dec_rnn_units=64, num_feats=6, num_labels=6, z_input=True):
        super(RVAEModel, self).__init__()
        self.enc_rnn_units = enc_rnn_units
        self.z_dim = z_dim
        self.dec_rnn_units = dec_rnn_units
        self.num_feats = num_feats
        self.num_labels = num_labels
        self.z_input = z_input
        self.encoder = RNNEncoder(enc_rnn_units)
        self.decoder = RNNDecoder(dec_rnn_units, num_feats, num_labels)
        self.fc_z = layers.Dense(6)
        self.fc_hidden = layers.Dense(3*self.dec_rnn_units)

    def __call__(self, x, y):
        batch_size, time_len, feat_dim = x.shape
        z, mu, log_var = self.encoder(x)

        decoder_outputs = []
        # initialize the decoder state with the z vector
        dec_init_state = tf.reshape(self.fc_hidden(z), [3, batch_size, -1])
        init_step = tf.zeros_like(x[:, 0:1, :])
        dec_input = tf.concat([init_step, x[:, :-1]], axis=1)
        if self.z_input:
            z_emb = self.fc_z(z)
            z_with_time = tf.tile(tf.expand_dims(
                z_emb, 1), [1, time_len, 1])
            dec_input = tf.concat([z_with_time, dec_input], axis=2)
        recon_output, _ = self.decoder(dec_input, dec_init_state, y)
        return recon_output, mu, log_var

    def sample(self, labels, max_len=125):
        """ generates samples conditioned on the given label """
        num_examples = int(labels.shape[0])
        z = tf.random_normal(shape=(num_examples, self.decoder.rnn_units))
        last_pred = tf.zeros(shape=(num_examples, 1, self.num_feats))
        preds = []
        last_state = tf.reshape(self.fc_hidden(z), [3, num_examples, -1])
        z_emb = self.fc_z(z)
        z_with_time = tf.expand_dims(z_emb, axis=1)
        for _ in range(max_len):
            if self.z_input:
                step_input = tf.concat([z_with_time, last_pred], axis=2)
            else:
                step_input = last_pred
            last_pred, last_state = self.decoder(
                step_input, last_state, labels)
            preds.append(last_pred)
        output = tf.concat(preds, axis=1)
        return output
