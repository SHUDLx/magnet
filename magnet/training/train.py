import magnet as mag

class Trainer:
	def __init__(self, models, data, optimizers):
		self._models = models
		self._data = data
		self._optimizers = optimizers

		from magnet.training.history import History
		self._history = History()

	def _optimize(self, dataloader, batch):
		raise NotImplementedError

	def _validate(self, dataloader, validation_batches):
		pass

	def train(self, epochs=1, batch_size=1, shuffle=True, **kwargs):
		from magnet._utils import get_tqdm; tqdm = get_tqdm()
		from magnet import data as data_module

		monitor_freq=kwargs.pop('monitor_freq', 10)
		validate_freq=kwargs.pop('validate_freq', monitor_freq)
		batch_size_val=kwargs.pop('batch_size_val', batch_size)
		shuffle_val=kwargs.pop('shuffle_val', False)

		self._on_training_start()

		if isinstance(self._data, data_module.Data):
			dataloader = {'train': iter(self._data(batch_size, shuffle))}

			if batch_size_val < 0: batch_size_val = batch_size
			dataloader['val'] = iter(self._data(batch_size_val, shuffle=shuffle_val, mode='val'))
		elif isinstance(self._data, (tuple, list)):
			dataloader = {'train': iter(self._data[0]), 'val': iter(self._data[1])}

		validation_batches=kwargs.pop('validation_batches', int(len(dataloader['val']) // validate_freq))

		self._batches_per_epoch = len(dataloader['train'])

		iterations = kwargs.pop('batch_size_val', int(epochs * self._batches_per_epoch))

		try: start_iteration = self._history['batches'][-1]
		except KeyError: start_iteration = 0

		progress_bar = tqdm(range(start_iteration, start_iteration + iterations), unit_scale=True,
							unit_divisor=self._batches_per_epoch, leave=False)

		for batch in progress_bar:
			is_last_batch = (batch == start_iteration + iterations - 1)

			try:
				if not batch % self._batches_per_epoch:
					self._on_epoch_start(int(batch * self._batches_per_epoch))
			except AttributeError: pass

			self._on_batch_start(batch)

			self._optimize(dataloader['train'], batch)

			self._on_batch_end(batch)

			if is_last_batch or (not batch % int(self._batches_per_epoch // validate_freq) and batch != 0):
				with mag.eval(*self._models): self._validate(dataloader['val'], validation_batches)

			if is_last_batch or (not batch % int(self._batches_per_epoch // monitor_freq) and batch != 0):
				self._monitor(batch, progress_bar=progress_bar)

			try:
				if not (batch + 1) % self._batches_per_epoch:
					self._on_epoch_end(int(batch // self._batches_per_epoch))
			except AttributeError: pass

		self._on_training_end()

	def show_history(self, keys=None, vs=None):
		xlabel = None

		if vs is None:
			vs = 'epochs' if self._history['batches'][-1] > self._batches_per_epoch else 'batches'
		vs = vs.lower()
		if vs == 'epochs':
			vs = [b / self._batches_per_epoch for b in self._history['batches']]
			xlabel = 'epochs'
		elif vs in ('batches', 'iterations'):
			vs = 'batches'
			xlabel = 'iterations'

		if keys is None:
			keys = [k for k in self._history.keys() if k not in ('batches', ) and k[:4] != 'val_']

		for k in keys:
			if 'loss' in k:
				self._history.show(k, log=True, x_key=vs, xlabel=xlabel)
			else:
				self._history.show(k, x_key=vs, xlabel=xlabel)

	def _on_training_start(self):
		pass

	def _on_epoch_start(self, epoch):
		pass

	def _on_batch_start(self, batch):
		pass

	def _on_batch_end(self, batch):
		pass

	def _monitor(self, batch, **kwargs):
		self._history.append('batches', batch)
		self._history.flush()

	def _on_epoch_end(self, epoch):
		pass

	def _on_training_end(self):
		pass

class SupervisedTrainer(Trainer):
	def __init__(self, model, data, loss, optimizer='adam', metrics=None):
		super().__init__([model], data, optimizers=None)

		self._optimizers = [self._get_optimizer(optimizer)]
		self._loss = loss
		self._set_metrics(metrics)

	def _optimize(self, dataloader, batch):
		optimizer = self._optimizers[0]

		loss = self._get_loss(dataloader)

		loss.backward()
		optimizer.step()
		optimizer.zero_grad()

	def _validate(self, dataloader, validation_batches):
		for _ in range(validation_batches): self._get_loss(dataloader, validation=True)

	def _get_loss(self, dataloader, validation=False):
		model = self._models[0]; loss_fn = self._loss

		x, y = next(dataloader)
		y_pred = model(x)

		loss = loss_fn(y_pred, y)

		self._history.append('loss', loss.item(), validation=validation, buffer=True)
		for k in self._metrics.keys():
			self._history.append(k, self._metrics[k](y_pred, y).item(), validation=validation, buffer=True)

		return loss

	def _get_optimizer(self, optimizer):
		from torch import optim

		if optimizer == 'adam':
			return optim.Adam(self._models[0].parameters(), amsgrad=True)

	def _set_metrics(self, metrics):
		from magnet.training import metrics as metrics_module
		if isinstance(metrics, str): self._metrics = {metrics: getattr(metrics_module, metrics.lower())}
		elif isinstance(metrics, (tuple, list)): self._metrics = {m: getattr(metrics_module, m.lower()) for m in metrics}
		elif isinstance(metrics, dict): self._metrics = metrics

	def _monitor(self, batch, **kwargs):
		super()._monitor(batch, **kwargs)
		progress_bar = kwargs.pop('progress_bar')

		loss = self._history['loss'][-1]; 
		try: 
			val_loss = self._history['val_loss'][-1]
			progress_bar.set_description(f'{loss:.2f}, {val_loss:.2f}', refresh=False)
		except KeyError: 
			progress_bar.set_description(f'{loss:.2f}', refresh=False)

class ClassifierTrainer(SupervisedTrainer):
	def __init__(self, model, data, optimizer='adam'):
		from torch import nn

		super().__init__(model, data, nn.CrossEntropyLoss(), optimizer, metrics='accuracy')
