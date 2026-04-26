declare module "react-pdf" {
  import type React from "react";

  export const Document: React.ComponentType<any>;
  export const Page: React.ComponentType<any>;
  export const pdfjs: {
    GlobalWorkerOptions: {
      workerSrc: string;
    };
    version: string;
  };
}
