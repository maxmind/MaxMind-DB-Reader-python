/* -*- Mode: C; indent-tabs-mode: t; c-basic-offset: 4; tab-width: 4 -*- */

#include <Python.h>
#include <maxminddb.h>

static PyTypeObject Reader_Type;
static PyObject *MaxMind_DB_Error;

typedef struct {
    PyObject_HEAD               /* no semicolon */
    MMDB_s * mmdb;
} Reader_obj;

static const MMDB_entry_data_list_s *handle_entry_data_list(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static const MMDB_entry_data_list_s *handle_map(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static const MMDB_entry_data_list_s *handle_array(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static void handle_uint128(const MMDB_entry_data_list_s *entry_data_list,
                           PyObject **py_obj);
static void handle_uint64(const MMDB_entry_data_list_s *entry_data_list,
                          PyObject **py_obj);
static bool file_is_readable(const char *filename);

#if PY_MAJOR_VERSION >= 3
    #define MOD_INIT(name) PyMODINIT_FUNC PyInit_ ## name(void)
    #define RETURN_MOD_INIT(m) return (m)
#else
    #define MOD_INIT(name) PyMODINIT_FUNC init ## name(void)
    #define RETURN_MOD_INIT(m) return
    #define PyInt_FromLong PyLong_FromLong
#endif


static PyObject *Reader_constructor(PyObject * self, PyObject * args)
{
    Reader_obj *obj;
    char *filename;

    if (!PyArg_ParseTuple(args, "s", &filename)) {
        return NULL;
    }

    if (!file_is_readable(filename)) {
        PyErr_Format(PyExc_ValueError,
                     "The file \"%s\" does not exist or is not readable.",
                     filename);
        return NULL;
    }

    obj = PyObject_New(Reader_obj, &Reader_Type);
    if (!obj) {
        return NULL;
    }

    MMDB_s *mmdb = (MMDB_s *)malloc(sizeof(MMDB_s));
    if (NULL == mmdb) {
        PyErr_NoMemory();
    }
    uint16_t status = MMDB_open(filename, MMDB_MODE_MMAP, mmdb);

    if (MMDB_SUCCESS != status) {
        PyErr_Format(
            MaxMind_DB_Error,
            "Error opening database file (%s). Is this a valid MaxMind DB file?",
            filename
            );
        Py_DECREF(obj);
        free(mmdb);
        return NULL;
    }

    obj->mmdb = mmdb;
    return (PyObject *)obj;
}

static void Reader_dealloc(PyObject * self)
{
    Reader_obj *obj = (Reader_obj *)self;
    if (obj->mmdb != NULL) {
        MMDB_close(obj->mmdb);
        free(obj->mmdb);
        obj->mmdb = NULL;
    }

    PyObject_Del(self);
}


static PyObject *Reader_get(PyObject * self, PyObject * args)
{
    char *ip_address = NULL;

    Reader_obj *mmdb_obj = (Reader_obj *)self;
    if (!PyArg_ParseTuple(args, "s", &ip_address)) {
        return NULL;
    }


    MMDB_s *mmdb = mmdb_obj->mmdb;

    if (NULL == mmdb) {
        PyErr_SetString(PyExc_ValueError,
                        "Attempt to read from a closed MaxMind DB.");
        return NULL;
    }

    int gai_error = MMDB_SUCCESS;
    int mmdb_error = MMDB_SUCCESS;
    MMDB_lookup_result_s result =
        MMDB_lookup_string(mmdb, ip_address, &gai_error,
                           &mmdb_error);

    if (MMDB_SUCCESS != gai_error) {
        PyErr_Format(PyExc_ValueError,
                     "The value \"%s\" is not a valid IP address.",
                     ip_address);
        return NULL;
    }

    if (MMDB_SUCCESS != mmdb_error) {
        PyErr_Format(MaxMind_DB_Error, "Error looking up %s", ip_address);
        return NULL;
    }

    MMDB_entry_data_list_s *entry_data_list = NULL;

    if (result.found_entry) {
        PyObject *py_obj = NULL;

        int status = MMDB_get_entry_data_list(&result.entry, &entry_data_list);
        if (MMDB_SUCCESS != status) {
            PyErr_Format(MaxMind_DB_Error,
                         "Error while looking up data for %s", ip_address);
        } else if (NULL != entry_data_list) {
            handle_entry_data_list(entry_data_list, &py_obj);
        }

        MMDB_free_entry_data_list(entry_data_list);
        return py_obj;
    }

    Py_RETURN_NONE;
}

static const MMDB_entry_data_list_s *handle_entry_data_list(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    switch (entry_data_list->entry_data.type) {
    case MMDB_DATA_TYPE_MAP:
        return handle_map(entry_data_list, py_obj);
    case MMDB_DATA_TYPE_ARRAY:
        return handle_array(entry_data_list, py_obj);
    case MMDB_DATA_TYPE_UTF8_STRING:
        *py_obj = PyUnicode_FromStringAndSize(
            (char *)entry_data_list->entry_data.utf8_string,
            entry_data_list->entry_data.data_size
            );
        break;
    case MMDB_DATA_TYPE_BYTES:
        *py_obj = PyByteArray_FromStringAndSize(
            (char *)entry_data_list->entry_data.bytes,
            entry_data_list->entry_data.data_size);
        break;
    case MMDB_DATA_TYPE_DOUBLE:
        *py_obj = PyFloat_FromDouble(entry_data_list->entry_data.double_value);
        break;
    case MMDB_DATA_TYPE_FLOAT:
        *py_obj = PyFloat_FromDouble(entry_data_list->entry_data.float_value);
        break;
    case MMDB_DATA_TYPE_UINT16:
        *py_obj = PyLong_FromLong( entry_data_list->entry_data.uint16);
        break;
    case MMDB_DATA_TYPE_UINT32:
        *py_obj = PyLong_FromLong(entry_data_list->entry_data.uint32);
        break;
    case MMDB_DATA_TYPE_BOOLEAN:
        *py_obj = PyBool_FromLong(entry_data_list->entry_data.boolean);
        break;
    case MMDB_DATA_TYPE_UINT64:
        handle_uint64(entry_data_list, py_obj);
        break;
    case MMDB_DATA_TYPE_UINT128:
        handle_uint128(entry_data_list, py_obj);
        break;
    case MMDB_DATA_TYPE_INT32:
        *py_obj = PyLong_FromLong(entry_data_list->entry_data.int32);
        break;
    default:
        PyErr_Format(MaxMind_DB_Error,
                     "Invalid data type arguments: %d",
                     entry_data_list->entry_data.type);
        return NULL;
    }
    return entry_data_list->next;
}

static const MMDB_entry_data_list_s *handle_map(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    *py_obj = PyDict_New();

    const uint32_t map_size = entry_data_list->entry_data.data_size;
    entry_data_list = entry_data_list->next;

    uint i;
    for (i = 0; i < map_size && entry_data_list; i++) {
        PyObject *key, *value;

        key = PyUnicode_FromStringAndSize(
            (char *)entry_data_list->entry_data.utf8_string,
            entry_data_list->entry_data.data_size
            );

        entry_data_list = entry_data_list->next;

        entry_data_list = handle_entry_data_list(entry_data_list,
                                                 &value);
        PyDict_SetItem(*py_obj, key, value);
        Py_DECREF(value);
        Py_DECREF(key);
    }
    return entry_data_list;
}

static const MMDB_entry_data_list_s *handle_array(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    const uint32_t size = entry_data_list->entry_data.data_size;

    *py_obj = PyList_New(size);
    entry_data_list = entry_data_list->next;

    uint i;
    for (i = 0; i < size && entry_data_list; i++) {
        PyObject *new_value;
        entry_data_list = handle_entry_data_list(entry_data_list,
                                                 &new_value);
        PyList_SET_ITEM(*py_obj, i, new_value);
    }
    return entry_data_list;
}

static void handle_uint128(const MMDB_entry_data_list_s *entry_data_list,
                           PyObject **py_obj)
{
    uint64_t high = 0;
    uint64_t low = 0;
#if MISSING_UINT128
    int i;
    for (i = 0; i < 8; i++) {
        high = (high << 8) | entry_data_list->entry_data.uint128[i];
    }

    for (i = 8; i < 16; i++) {
        low = (low << 8) | entry_data_list->entry_data.uint128[i];
    }
#else
    high = entry_data_list->entry_data.uint128 >> 64;
    low = (uint64_t)entry_data_list->entry_data.uint128;
#endif

    char *num_str;
    int status = asprintf(&num_str, "%016" PRIX64 "%016" PRIX64, high, low);

    if (status <= 0) {
        PyErr_NoMemory();
    }

    *py_obj = PyLong_FromString(num_str, NULL, 10);

    free(num_str);
}

static void handle_uint64(const MMDB_entry_data_list_s *entry_data_list,
                          PyObject **py_obj)
{
    char *int_str;
    int status = asprintf(&int_str, "%" PRIu64,
                          entry_data_list->entry_data.uint64 );
    if (status <= 0) {
        PyErr_NoMemory();
    }

    *py_obj = PyLong_FromString(int_str, NULL, 10);
    free(int_str);
}

static bool file_is_readable(const char *filename)
{
    FILE *file = fopen(filename, "r");
    if (file) {
        fclose(file);
        return true;
    }
    return false;
}

static PyMethodDef Reader_methods[] = {
    { "get", Reader_get, 1, "Get record for IP address" },
    { NULL,  NULL,       0, NULL                        }
};

static PyTypeObject Reader_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "maxminddb",
    sizeof(Reader_obj),
    0,
    Reader_dealloc,             /*tp_dealloc */
    0,                          /*tp_print */
    0,                          /*tp_getattr */
    0,                          /*tp_setattr */
    0,                          /*tp_compare */
    0,                          /*tp_repr */
    0,                          /*tp_as_number */
    0,                          /*tp_as_sequence */
    0,                          /*tp_as_mapping */
    0,                          /*tp_hash */
#if PY_MAJOR_VERSION >= 3
    0,                          /* tp_call */
    0,                          /* tp_str */
    0,                          /* tp_getattro */
    0,                          /* tp_setattro */
    0,                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,         /* tp_flags */
    "maxminddb.Reader object",  /* tp_doc */
    0,                          /* tp_traverse */
    0,                          /* tp_clear */
    0,                          /* tp_richcompare */
    0,                          /* tp_weaklistoffset */
    0,                          /* tp_iter */
    0,                          /* tp_iternext */
    Reader_methods,             /* tp_methods */
    0,                          /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    0,                          /* tp_init */
    0,                          /* tp_alloc */
    0,                          /* tp_new */
#endif
};

static PyMethodDef MaxMindDB_methods[] = {
    { "Reader", Reader_constructor, 1,
      "Creates a new maxminddb.Reader object" },
    { NULL,     NULL,               0,NULL}
};

#if PY_MAJOR_VERSION >= 3
static struct PyModuleDef MaxMindDB_module = {
    PyModuleDef_HEAD_INIT,
    "maxminddb",                               /* m_name */
    "This is a module to read mmdb databases", /* m_doc */
    -1,                                        /* m_size */
    MaxMindDB_methods,                         /* m_methods */
    NULL,                                      /* m_reload */
    NULL,                                      /* m_traverse */
    NULL,                                      /* m_clear */
    NULL,                                      /* m_free */
};
#endif

MOD_INIT(maxminddb){
    PyObject *m;

#if PY_MAJOR_VERSION >= 3
    m = PyModule_Create(&MaxMindDB_module);
    Reader_Type.tp_new = PyType_GenericNew;
    if (PyType_Ready(&Reader_Type) < 0) {
        return NULL;
    }
    PyModule_AddObject(m, "maxminddb", (PyObject *)&Reader_Type);
    Py_INCREF(&Reader_Type);
#else
    m = Py_InitModule("maxminddb", MaxMindDB_methods);
#endif

    RETURN_MOD_INIT(m);
}
