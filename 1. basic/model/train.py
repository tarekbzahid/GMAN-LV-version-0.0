import time
import datetime
import torch
import torch.jit
from utils.utils_ import log_string
from model.model_ import *
from utils.utils_ import load_data

def get_free_cuda_device(args):
    # Check if GPU is available
    if torch.cuda.is_available():
        # Set device to the specified CUDA device
        return torch.device('cuda', args.cuda_device)
    else:
        # CUDA not available, use CPU
        return torch.device('cpu')


def train(model, args, log, loss_criterion, optimizer, scheduler):
    # Get the free CUDA device
    device = get_free_cuda_device(args)

    # Move model to GPU if available
    model.to(device)
    # Move loss criterion to GPU if available
    loss_criterion.to(device)

    # Load data
    (trainX, trainTE, trainY, valX, valTE, valY, testX, testTE,
     testY, SE, mean, std) = load_data(args)
    log_string(log, 'Data loaded!...')

    num_train, _, num_vertex = trainX.shape
    log_string(log, '**** Training model ****')

    num_val = valX.shape[0]

    train_num_batch = math.ceil(num_train / args.batch_size)
    val_num_batch = math.ceil(num_val / args.batch_size)

    wait = 0
    val_loss_min = float('inf')
    best_model_wts = None
    train_total_loss = []
    val_total_loss = []

    if torch.cuda.is_available():
        # Move data to GPU
        trainX = trainX.to(device)
        trainTE = trainTE.to(device)
        trainY = trainY.to(device)
        valX = valX.to(device)
        valTE = valTE.to(device)
        valY = valY.to(device)
        testX = testX.to(device)
        testTE = testTE.to(device)
        testY = testY.to(device)
        SE = SE.to(device)
        mean = mean.to(device)
        std = std.to(device)
        log_string(log, "Data moved to GPU")

    # Training & Validation
    for epoch in range(args.max_epoch):
        if wait >= args.patience:
            log_string(log, f'Early stop at epoch: {epoch:04d}')
            break

        # Shuffle training data
        permutation = torch.randperm(num_train)
        trainX = trainX[permutation]
        trainTE = trainTE[permutation]
        trainY = trainY[permutation]

        # Train
        start_train = time.time()
        model.train()
        train_loss = 0
        for batch_idx in range(train_num_batch):
            start_idx = batch_idx * args.batch_size
            end_idx = min(num_train, (batch_idx + 1) * args.batch_size)
            X = trainX[start_idx: end_idx]
            TE = trainTE[start_idx: end_idx]
            label = trainY[start_idx: end_idx]
            optimizer.zero_grad()
            X = X.to(device)
            TE = TE.to(device)
            pred = model(X, TE)
            pred = pred * std + mean
            loss_batch = loss_criterion(pred, label)
            train_loss += float(loss_batch) * (end_idx - start_idx)
            loss_batch.backward()
            optimizer.step()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            if (batch_idx+1) % 5 == 0:
                print(f'Training batch: {batch_idx+1} in epoch:{epoch}, training batch loss:{loss_batch:.4f}')

            del X, TE, label, pred, loss_batch

        train_loss /= num_train
        train_total_loss.append(train_loss)
        end_train = time.time()

        # Validation loss
        start_val = time.time()
        val_loss = 0
        model.eval()
        with torch.no_grad():
            for batch_idx in range(val_num_batch):
                start_idx = batch_idx * args.batch_size
                end_idx = min(num_val, (batch_idx + 1) * args.batch_size)
                X = valX[start_idx: end_idx]
                TE = valTE[start_idx: end_idx]
                label = valY[start_idx: end_idx]
                pred = model(X, TE)
                pred = pred * std + mean
                loss_batch = loss_criterion(pred, label)
                val_loss += loss_batch * (end_idx - start_idx)
                del X, TE, label, pred, loss_batch

        val_loss /= num_val
        val_total_loss.append(val_loss)
        end_val = time.time()
        log_string(log, '%s | epoch: %04d/%d, training time: %.1fs, inference time: %.1fs' %
                   (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), epoch + 1,
                    args.max_epoch, end_train - start_train, end_val - start_val))
        log_string(log, f'train loss: {train_loss:.4f}, val_loss: {val_loss:.4f}')

        if val_loss <= val_loss_min:
            log_string(log, f'val loss decrease from {val_loss_min:.4f} to {val_loss:.4f}, saving model to {args.model_file}')
            wait = 0
            val_loss_min = val_loss
            best_model_wts = model.state_dict()
            torch.save(best_model_wts, './basic/data/best_model_weights.pt')
        else:
            wait += 1

        scheduler.step()

    model.load_state_dict(best_model_wts)
    torch.save(model, args.model_file)

    log_string(log, f'Training and validation are completed, and model has been stored as {args.model_file}')
    return train_total_loss, val_total_loss
