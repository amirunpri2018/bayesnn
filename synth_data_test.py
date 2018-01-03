
import torch
import torch.nn.functional as F
from torch.autograd import Variable
from torch.nn import Module, Linear
from torch.nn.parameter import Parameter

import numpy as np
from tqdm import tqdm
import matplotlib.pylab as plt


class MLP(Module):
    def __init__(self, input_size, hidden_dim, output_size):
        super(MLP, self).__init__()

        # Params
        self.hidden_dim = hidden_dim

        # Layers / nn objects
        self.dense1 = Linear(input_size, hidden_dim)
        self.dense2 = Linear(hidden_dim, hidden_dim)
        self.dense3 = Linear(hidden_dim, hidden_dim)
        self.dense4 = Linear(hidden_dim, output_size)

    def forward(self, x):

        x = F.relu(self.dense1(x))
        x = F.relu(self.dense2(x))
        x = F.relu(self.dense3(x))
        x = self.dense4(x)

        return x


def log_gaussian_posterior(x, mu, sigma):

    expr = -0.5 * torch.pow(x - mu, 2) / torch.pow(sigma, 2) - torch.log(sigma)

    return expr


def log_gaussian_prior(x):

    expr = -0.5 * torch.pow(x, 2)

    return expr


def log_spikeslab_prior(x):

    expr = -0.5 * torch.pow(x, 2)

    return expr


class BayesLinear(Module):

    def __init__(self, in_features, out_features, bias=True):
        super(BayesLinear, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.bias = bias

        self.w_mu = Parameter(torch.Tensor(out_features, in_features))
        self.w_rho = Parameter(torch.Tensor(out_features, in_features))
        if bias:
            self.b_mu = Parameter(torch.Tensor(out_features))
            self.b_rho = Parameter(torch.Tensor(out_features))
        else:
            self.register_parameter('b_mu', None)
            self.register_parameter('b_rho', None)

        self.log_q = None
        self.log_p = None
        self.kl = None

        self.reset_parameters()

    def reset_parameters(self):

        # Initialize weights
        stdv = 1. / np.sqrt(self.w_mu.size(1))
        self.w_mu.data.uniform_(-stdv, stdv)
        self.w_rho.data.fill_(-3)

        # Initialize biases
        if self.bias is not None:
            self.b_mu.data.uniform_(-stdv, stdv)
            self.b_rho.data.fill_(-3)

    def get_weights(self):

        return (self.w_mu, self.w_rho), (self.b_mu, self.b_rho)

    def forward(self, input, infer=False):

        if infer:
            return F.linear(input, self.w_mu, self.b_mu)

        # Sample weights from normal distribution
        w_epsilon = torch.normal(mean=0, std=torch.ones(self.w_mu.size()))
        w_sigma = torch.log(1.0 + torch.exp(self.w_rho))
        weight = self.w_mu + w_sigma * Variable(w_epsilon, requires_grad=False)

        # Sample biases from normal distribution
        b_epsilon = torch.normal(mean=0, std=torch.ones(self.b_mu.size()))
        b_sigma = torch.log(1.0 + torch.exp(self.b_rho))
        bias = self.b_mu + b_sigma * Variable(b_epsilon, requires_grad=False)

        self.log_q = log_gaussian_posterior(weight, self.w_mu, w_sigma).sum()
        self.log_q += log_gaussian_posterior(bias, self.b_mu, b_sigma).sum()

        self.log_p = log_gaussian_prior(weight).sum()
        self.log_p += log_gaussian_prior(bias).sum()

        self.kl = self.log_q - self.log_p

        return F.linear(input, weight, bias)

    def __repr__(self):
        return self.__class__.__name__ + ' (' \
            + str(self.in_features) + ' -> ' \
            + str(self.out_features) + ')'


class BayesMLP(Module):
    def __init__(self, input_size, hidden_dim, output_size):
        super(BayesMLP, self).__init__()

        # Params
        self.hidden_dim = hidden_dim

        # Layers / nn objects
        self.dense1 = BayesLinear(input_size, hidden_dim)
        self.dense2 = BayesLinear(hidden_dim, hidden_dim)
        self.dense3 = BayesLinear(hidden_dim, hidden_dim)
        self.dense4 = BayesLinear(hidden_dim, output_size)

    def get_weights(self):

        list_weights = []
        for layer in [self.dense1, self.dense2, self.dense3]:
            weights = layer.get_weights()
            list_weights.append(weights[0])
            list_weights.append(weights[1])

        return list_weights

    def forward(self, x, infer=False):

        x = F.relu(self.dense1(x, infer=infer))
        x = F.relu(self.dense2(x, infer=infer))
        x = F.relu(self.dense3(x, infer=infer))
        x = self.dense4(x, infer=infer)

        self.kl = self.dense1.kl.sum() + self.dense2.kl.sum() + self.dense3.kl.sum() + self.dense4.kl.sum()

        return x


def forward_pass_samples(model, X, y, criterion):

    list_preds = []

    kl = 0

    for i in range(X.size(0)):
        pred = model(X[i].view(1, -1))
        list_preds.append(pred)

        kl += model.kl / (X.size(0))  # divide by batch size

    preds = torch.cat(list_preds)
    log_likelihood = criterion(preds, y)

    return log_likelihood, kl


def get_metrics(model, X, Y):

    x = np.linspace(-1, 1.2, 1000).reshape(-1, 1)
    x_var = Variable(torch.FloatTensor(x))

    if isinstance(model, BayesMLP):
        # Make several predictions
        list_preds = []
        for i in range(100):
            list_preds.append(model(x_var).data.cpu().numpy())
        preds = np.stack(list_preds)

        plt.scatter(X, Y, s=5, color="C0")
        plt.plot(x, np.median(preds, 0), color="C1")

        upper = np.median(preds, 0) + np.std(preds, 0)
        lower = np.median(preds, 0) - np.std(preds, 0)

        plt.fill_between(x[:, 0], lower[:, 0], upper[:, 0], color='C1', alpha=0.2)

        plt.show()

    else:
        preds = model(x_var).data.cpu().numpy()

        plt.scatter(X, Y, s=5, color="C0")
        plt.plot(x, preds, color="C1")
        plt.show()


def train_synth():

    X_train = np.random.uniform(0, 0.5, 10000).reshape(-1, 1)
    eps = np.random.normal(0, 0.02, X_train.shape[0]).reshape(-1, 1)
    Y_train = X_train + 0.3 * np.sin(2 * np.pi * (X_train + eps)) + 0.3 * np.sin(4 * np.pi * (X_train + eps)) + eps

    # Create a list of batches
    num_elem = X_train.shape[0]
    batch_size = 128
    num_batches = num_elem / batch_size
    list_batches = np.array_split(np.arange(num_elem), num_batches)

    # Load model
    model = BayesMLP(1, 128, 1)
    print(model)
    criterion = torch.nn.MSELoss()
    optim = torch.optim.Adam(model.parameters(), lr=1E-3)

    for epoch in range(100):

        list_likelihood_loss = []
        list_kl_loss = []

        for batch_idxs in tqdm(list_batches[:10]):

            # Reset gradients
            optim.zero_grad()

            # Load batch
            start, end = batch_idxs[0], batch_idxs[-1] + 1
            X_batch, Y_batch = X_train[start:end], Y_train[start:end]
            X_batch, Y_batch = torch.FloatTensor(X_batch), torch.FloatTensor(Y_batch)
            X_var, Y_var = Variable(X_batch), Variable(Y_batch)

            # Forward pass
            likelihood_loss, kl_loss = forward_pass_samples(model, X_var, Y_var, criterion)
            loss = likelihood_loss + kl_loss

            # Backward pass
            loss.backward()
            optim.step()

            list_likelihood_loss.append(likelihood_loss.data.cpu().numpy()[0])
            list_kl_loss.append(kl_loss.data.cpu().numpy()[0])

        print("\n")
        print("Likelihood", np.mean(list_likelihood_loss), "KL", np.mean(list_kl_loss))
        print("\n")

    print("\n")
    print("Likelihood", np.mean(list_likelihood_loss), "KL", np.mean(list_kl_loss))
    get_metrics(model, X_train, Y_train)
    print("\n")


if __name__ == '__main__':

    train_synth()
