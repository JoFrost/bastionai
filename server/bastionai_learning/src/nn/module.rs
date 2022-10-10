use std::io::Cursor;
use std::sync::{Arc, Mutex, RwLock};

use super::{LossType, Parameters};
use crate::data::privacy_guard::PrivacyGuard;
use crate::serialization::{BinaryModule, SizedObjectsBytes};
use tch::{nn::VarStore, Device, TchError, TrainableCModule};
use tch::{CModule, Tensor};

/// Contains useful information at the module level to carry out DP-SGD
/// (delta, batch sampling rate, etc.)
#[derive(Debug, Clone)]
pub struct DpSGDContext {
    delta: f32,
    batch_sampling_rate: f32,
    empty_guard: PrivacyGuard<()>,
}

impl DpSGDContext {
    pub fn delta(&self) -> f32 {
        self.delta
    }
    pub fn batch_sampling_rate(&self) -> f32 {
        self.batch_sampling_rate
    }
    pub fn empty_guard(&self) -> &PrivacyGuard<()> {
        &self.empty_guard
    }
}

/// Represents the forward pass function of a module.
///
/// The forward pass can be applied to a set of inputs using
/// the `forward` method.
///
/// This struct is needed because parameters mutably borrow part of a
/// module (its parameters) pereventing any other code from immutably
/// borrowing its forward pass function. This can be circumventing by
/// returning the forward pass as a standalone struct at the same time
/// as the parameters.
#[derive(Debug, Clone)]
pub struct Forward<'a> {
    c_module: &'a TrainableCModule,
    dp_sgd_context: Arc<RwLock<Option<DpSGDContext>>>,
}

impl<'a> Forward<'a> {
    pub(crate) fn forward_inner(&self, inputs: &[Tensor]) -> Result<Tensor, TchError> {
        self.c_module.forward_ts(inputs)
    }

    pub fn forward(
        &self,
        inputs: Vec<PrivacyGuard<Tensor>>,
    ) -> Result<PrivacyGuard<Tensor>, TchError> {
        if inputs.len() > 0 {
            *self.dp_sgd_context.write().unwrap() = Some(DpSGDContext {
                delta: inputs[0].map_context(|x| x.delta()),
                batch_sampling_rate: inputs[0].batch_size()? as f32
                    / inputs[0].map_context(|x| x.nb_samples()) as f32,
                empty_guard: inputs[0].empty(),
            })
        }
        PrivacyGuard::apply_forward(self.clone(), inputs)
    }
}

/// A Trainable Model
///
/// Contains a reference to a [`tch::TrainableCModule`]
/// obtained from bytes data that has been serialized with
/// `torch.jit.save`, a VarStore that holds the models
/// parameters and some contaxt data in a `DpSGDContext`.
///
/// The context is shared with the [`Forward`] and [`Parameters`] objects
/// returned by methods.
#[derive(Debug)]
pub struct Module {
    c_module: TrainableCModule,
    var_store: VarStore,
    dp_sgd_context: Arc<RwLock<Option<DpSGDContext>>>,
}

impl Module {
    /// Loads a module serialized with `torch.jit.save` from a file.
    pub fn load_from_file(file_path: &str, device: Device) -> Result<Self, TchError> {
        let var_store = VarStore::new(device);
        let c_module = TrainableCModule::load(file_path, var_store.root())?;
        Ok(Module {
            c_module,
            var_store,
            dp_sgd_context: Arc::new(RwLock::new(None)),
        })
    }
    /// Returns the forward pass of the module as a standalone [`Forward`] struct.
    pub fn forward_fn<'a>(&'a self) -> Forward<'a> {
        Forward {
            c_module: &self.c_module,
            dp_sgd_context: Arc::clone(&self.dp_sgd_context),
        }
    }
    /// Get the model's forward pass as a standalone [`Forward`] struct
    /// and parameters wrapped in a [`Parameter::Standard`] variant.
    ///
    /// The parameters can be used to train the model without differential privacy with an [`Optimizer`].
    pub fn parameters<'a>(&'a mut self) -> (Forward<'a>, Parameters<'a>) {
        (
            Forward {
                c_module: &self.c_module,
                dp_sgd_context: Arc::clone(&self.dp_sgd_context),
            },
            Parameters::standard(&mut self.var_store, Arc::clone(&self.dp_sgd_context)),
        )
    }

    /// Get the model's forward pass as a standalone [`Forward`] struct
    /// and parameters wrapped in a [`Parameter::Private`] variant.
    ///
    /// The parameters can be used to train the model with differential privacy with an [`Optimizer`].
    pub fn private_parameters<'a>(
        &'a mut self,
        eps: f32,
        max_grad_norm: f32,
        loss_type: LossType,
    ) -> (Forward<'a>, Parameters<'a>) {
        (
            Forward {
                c_module: &self.c_module,
                dp_sgd_context: Arc::clone(&self.dp_sgd_context),
            },
            Parameters::private(
                &mut self.var_store,
                eps,
                max_grad_norm,
                loss_type,
                Arc::clone(&self.dp_sgd_context),
            ),
        )
    }
    /// Moves all the parameters to the specified device.
    pub fn set_device(&mut self, device: Device) {
        self.var_store.set_device(device);
    }
}

impl TryFrom<SizedObjectsBytes> for Module {
    type Error = TchError;

    fn try_from(mut value: SizedObjectsBytes) -> Result<Self, Self::Error> {
        let object = value.next().ok_or(TchError::FileFormat(String::from(
            "Invalid data, expected at least one object in stream.",
        )))?;
        let vs = VarStore::new(Device::Cpu);
        Ok(Module {
            c_module: TrainableCModule::load_data(&mut &object[..], vs.root())?,
            var_store: vs,
            dp_sgd_context: Arc::new(RwLock::new(None)),
        })
    }
}

impl TryFrom<&BinaryModule> for Module {
    type Error = TchError;

    fn try_from(value: &BinaryModule) -> Result<Self, Self::Error> {
        let vs = VarStore::new(Device::Cpu);
        Ok(Module {
            c_module: TrainableCModule::load_data(&mut &value.0[..], vs.root())?,
            var_store: vs,
            dp_sgd_context: Arc::new(RwLock::new(None)),
        })
    }
}
impl TryFrom<&Module> for SizedObjectsBytes {
    type Error = TchError;

    fn try_from(value: &Module) -> Result<Self, Self::Error> {
        let mut module_bytes = SizedObjectsBytes::new();
        let mut buf = Vec::new();
        value.var_store.save_to_stream(&mut buf)?;
        module_bytes.append_back(buf);
        Ok(module_bytes)
    }
}

pub type CheckPoint = Vec<(String, Mutex<Tensor>)>;

impl TryFrom<&CheckPoint> for SizedObjectsBytes {
    type Error = TchError;

    fn try_from(value: &CheckPoint) -> Result<Self, Self::Error> {
        println!("&CheckPoint -> SizedObjectBytes");
        let mut var_store = VarStore::new(Device::Cpu);
        let mut stream: Vec<u8> = vec![];
        value.iter().for_each(|(n, t)| {
            let t_guard = t.lock().unwrap();
            let capacity = t_guard.numel() * t_guard.f_kind().unwrap().elt_size_in_bytes();
            let mut bytes = vec![0; capacity];
            t_guard.copy_data_u8(&mut bytes[..], t_guard.numel());
            n.as_bytes().to_vec().drain(..).for_each(|v| stream.push(v));
            bytes.drain(..).for_each(|v| stream.push(v));
        });
        let stream = Cursor::new(stream);

        var_store.load_from_stream(stream).unwrap();
        println!("Loading into varstore");
        let data = vec![];
        let module = Module {
            c_module: TrainableCModule::load_data(&mut data.as_slice(), var_store.root())?,
            var_store,
            dp_sgd_context: Arc::new(RwLock::new(None)),
        };
        println!("{:#?}", module);
        let output: SizedObjectsBytes = (&module).try_into().unwrap();
        Ok(output)
    }
}
